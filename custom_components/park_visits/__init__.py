"""The Park Visits integration.

Fetches real parks near a configurable centre point from the Google Places
API, ranked by rating, exposing each as a geo_location entity (for the Map
card) plus a summary sensor. Also registers the `park_visits.rate_park`
service so a dashboard card can record your own rating/note for a park.
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_API_KEY,
    CONF_IMMICH_API_KEY,
    CONF_IMMICH_MAX_ASSETS,
    CONF_IMMICH_URL,
    DEFAULT_IMMICH_MAX_ASSETS,
    DOMAIN,
    MAX_OUR_RATING,
    MIN_OUR_RATING,
    SERVICE_ATTR_DISLIKED,
    SERVICE_ATTR_FACILITIES_RATING,
    SERVICE_ATTR_FILENAME,
    SERVICE_ATTR_LIKED,
    SERVICE_ATTR_NOTE,
    SERVICE_ATTR_PARKING_RATING,
    SERVICE_ATTR_PERSON_RATINGS,
    SERVICE_ATTR_PLACE_ID,
    SERVICE_ATTR_PLAYGROUND_RATING,
    SERVICE_ATTR_QUERY,
    SERVICE_ATTR_SCENERY_RATING,
    SERVICE_ATTR_TAG_ID,
    SERVICE_ATTR_VISIT_DATE,
    SERVICE_ATTR_WILDLIFE_RATING,
    SERVICE_ADD_PARK,
    SERVICE_CLEAR_NEXT_PARK,
    SERVICE_CLEAR_PARK_TAG,
    SERVICE_DELETE_PHOTO,
    SERVICE_DELETE_REVIEW,
    SERVICE_RATE_PARK,
    SERVICE_REMOVE_PARK,
    SERVICE_SET_NEXT_PARK,
    SERVICE_SET_PARK_TAG,
)
from .coordinator import ParkVisitsCoordinator
from .frontend import async_register_frontend
from .immich import ImmichClient, ImmichError
from .geocoding import GeocodeError, async_place_details, async_search_places
from .storage import (
    ManualParkStore,
    ParkListCache,
    ParkPlanStore,
    ParkReviewStore,
    ParkTagStore,
)
from .views import async_delete_photo_files, async_register_views

PLATFORMS = ["geo_location", "sensor", "button"]

_RATING = vol.All(vol.Coerce(float), vol.Range(min=MIN_OUR_RATING, max=MAX_OUR_RATING))

RATE_PARK_SCHEMA = vol.Schema(
    {
        vol.Required(SERVICE_ATTR_PLACE_ID): cv.string,
        # ISO date, not a full timestamp — this is "the day we went", chosen
        # by whoever writes the review (defaults to today client-side, but
        # can be back-dated). The only thing a review actually requires.
        vol.Required(SERVICE_ATTR_VISIT_DATE): vol.All(cv.string, vol.Match(r"^\d{4}-\d{2}-\d{2}$")),
        # {person_id: rating}, one entry per configured person who was
        # actually rated this visit — see const.CONF_PEOPLE. Nobody is
        # required, and an id not in the currently configured people list
        # (e.g. someone since removed) is simply ignored downstream.
        vol.Optional(SERVICE_ATTR_PERSON_RATINGS, default=dict): vol.Schema({cv.string: _RATING}),
        vol.Optional(SERVICE_ATTR_PLAYGROUND_RATING): _RATING,
        vol.Optional(SERVICE_ATTR_SCENERY_RATING): _RATING,
        vol.Optional(SERVICE_ATTR_WILDLIFE_RATING): _RATING,
        vol.Optional(SERVICE_ATTR_FACILITIES_RATING): _RATING,
        vol.Optional(SERVICE_ATTR_PARKING_RATING): _RATING,
        vol.Optional(SERVICE_ATTR_LIKED, default=""): cv.string,
        vol.Optional(SERVICE_ATTR_DISLIKED, default=""): cv.string,
        vol.Optional(SERVICE_ATTR_NOTE, default=""): cv.string,
    }
)

DELETE_REVIEW_SCHEMA = vol.Schema({vol.Required(SERVICE_ATTR_PLACE_ID): cv.string})

SET_NEXT_PARK_SCHEMA = vol.Schema({vol.Required(SERVICE_ATTR_PLACE_ID): cv.string})

CLEAR_NEXT_PARK_SCHEMA = vol.Schema({})

DELETE_PHOTO_SCHEMA = vol.Schema(
    {
        vol.Required(SERVICE_ATTR_PLACE_ID): cv.string,
        vol.Required(SERVICE_ATTR_FILENAME): cv.string,
    }
)

SET_PARK_TAG_SCHEMA = vol.Schema(
    {
        vol.Required(SERVICE_ATTR_PLACE_ID): cv.string,
        vol.Required(SERVICE_ATTR_TAG_ID): cv.string,
    }
)

CLEAR_PARK_TAG_SCHEMA = vol.Schema({vol.Required(SERVICE_ATTR_PLACE_ID): cv.string})

# Either identify the park exactly (place_id) or let Google's top match
# decide (query). The card always sends a place_id it got from the search
# endpoint; query exists so this is usable from an automation.
ADD_PARK_SCHEMA = vol.Schema(
    vol.All(
        {
            vol.Optional(SERVICE_ATTR_PLACE_ID): cv.string,
            vol.Optional(SERVICE_ATTR_QUERY): cv.string,
        },
        cv.has_at_least_one_key(SERVICE_ATTR_PLACE_ID, SERVICE_ATTR_QUERY),
    )
)

REMOVE_PARK_SCHEMA = vol.Schema({vol.Required(SERVICE_ATTR_PLACE_ID): cv.string})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Park Visits from a config entry."""
    reviews = ParkReviewStore(hass, entry.entry_id)
    await reviews.async_load()

    park_cache = ParkListCache(hass, entry.entry_id)
    plan = ParkPlanStore(hass, entry.entry_id)
    await plan.async_load()
    manual = ManualParkStore(hass, entry.entry_id)
    await manual.async_load()
    coordinator = ParkVisitsCoordinator(hass, entry, reviews, park_cache, plan, manual)

    # Restoring the previous park list keeps a restart free: Google is only
    # contacted when there's nothing cached for the current settings (first
    # setup, or after the centre point/radius/count changed).
    if not await coordinator.async_load_cached():
        await coordinator.async_config_entry_first_refresh()

    # Immich is optional: with no URL/key configured the client reports
    # itself unconfigured and every Immich code path degrades to "no photos"
    # rather than erroring.
    park_tags = ParkTagStore(hass, entry.entry_id)
    await park_tags.async_load()
    immich = ImmichClient(
        hass,
        entry.options.get(CONF_IMMICH_URL, ""),
        entry.options.get(CONF_IMMICH_API_KEY, ""),
        entry.options.get(CONF_IMMICH_MAX_ASSETS, DEFAULT_IMMICH_MAX_ASSETS),
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "reviews": reviews,
        "tags": park_tags,
        "immich": immich,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    async def _async_handle_rate_park(call: ServiceCall) -> None:
        place_id = call.data[SERVICE_ATTR_PLACE_ID]
        known_ids = {park.place_id for park in coordinator.data} if coordinator.data else set()
        if place_id not in known_ids:
            raise HomeAssistantError(
                f"Unknown park place_id '{place_id}' — it isn't in the current "
                "tracked list, so a review can't be attached to it"
            )
        await coordinator.async_submit_review(
            place_id,
            call.data.get(SERVICE_ATTR_PERSON_RATINGS) or {},
            call.data[SERVICE_ATTR_VISIT_DATE],
            playground_rating=call.data.get(SERVICE_ATTR_PLAYGROUND_RATING),
            scenery_rating=call.data.get(SERVICE_ATTR_SCENERY_RATING),
            wildlife_rating=call.data.get(SERVICE_ATTR_WILDLIFE_RATING),
            facilities_rating=call.data.get(SERVICE_ATTR_FACILITIES_RATING),
            parking_rating=call.data.get(SERVICE_ATTR_PARKING_RATING),
            note=call.data[SERVICE_ATTR_NOTE],
            liked=call.data[SERVICE_ATTR_LIKED],
            disliked=call.data[SERVICE_ATTR_DISLIKED],
        )

    async def _async_handle_delete_review(call: ServiceCall) -> None:
        place_id = call.data[SERVICE_ATTR_PLACE_ID]
        # Drop the record first so the photos can't be re-listed mid-delete,
        # then remove the files it pointed at.
        filenames = await coordinator.async_delete_review(place_id)
        await async_delete_photo_files(hass, place_id, filenames)

    async def _async_handle_set_next_park(call: ServiceCall) -> None:
        place_id = call.data[SERVICE_ATTR_PLACE_ID]
        known_ids = {park.place_id for park in coordinator.data} if coordinator.data else set()
        if place_id not in known_ids:
            raise HomeAssistantError(
                f"Unknown park place_id '{place_id}' — it isn't in the current tracked list"
            )
        await coordinator.async_set_next_park(place_id)

    async def _async_handle_clear_next_park(call: ServiceCall) -> None:
        await coordinator.async_clear_next_park()

    async def _async_handle_set_park_tag(call: ServiceCall) -> None:
        place_id = call.data[SERVICE_ATTR_PLACE_ID]
        tag_id = call.data[SERVICE_ATTR_TAG_ID]
        if not immich.configured:
            raise HomeAssistantError(
                "No Immich server is configured — add its URL and API key in "
                "the Park Visits options before tagging parks"
            )
        # Resolve the name now so the UI can still label the tag when Immich
        # is unreachable later. A lookup failure isn't fatal: the id is the
        # part that actually matters.
        tag_name = ""
        try:
            tag_name = next(
                (tag.name for tag in await immich.async_list_tags() if tag.id == tag_id), ""
            )
        except ImmichError as err:
            raise HomeAssistantError(f"Could not reach Immich: {err}") from err
        if not tag_name:
            raise HomeAssistantError(f"Immich has no tag with id '{tag_id}'")
        await park_tags.async_set(place_id, tag_id, tag_name)

    async def _async_handle_clear_park_tag(call: ServiceCall) -> None:
        await park_tags.async_clear(call.data[SERVICE_ATTR_PLACE_ID])

    async def _async_handle_add_park(call: ServiceCall) -> None:
        """Track a park the ranked search never returns.

        A place_id is used as-is; free text resolves to Google's top match.
        Either way this is one cheap Text Search at most — never a Nearby
        Search, so adding a park doesn't touch the paid ranked query.
        """
        api_key = entry.options.get(CONF_API_KEY)
        if not api_key:
            raise HomeAssistantError("No Google Places API key is configured")

        place_id = call.data.get(SERVICE_ATTR_PLACE_ID)
        query = call.data.get(SERVICE_ATTR_QUERY)

        candidate = None
        try:
            if place_id:
                # Place Details, not Text Search: searching for an id as
                # though it were a name matches nothing, which is exactly how
                # this failed when the card (which always sends an id) used
                # it. Details also returns the rating, so a park added this
                # way sorts correctly straight away.
                candidate = await async_place_details(hass, api_key, place_id)
            else:
                results = await async_search_places(hass, api_key, query)
                if results:
                    candidate = results[0]
        except GeocodeError as err:
            raise HomeAssistantError(f"Google couldn't resolve that park: {err}") from err

        if candidate is None:
            raise HomeAssistantError(f"Google returned no match for {query!r}")

        await coordinator.async_add_manual_park(candidate)

    async def _async_handle_remove_park(call: ServiceCall) -> None:
        place_id = call.data[SERVICE_ATTR_PLACE_ID]
        if not await coordinator.async_remove_manual_park(place_id):
            raise HomeAssistantError(
                f"'{place_id}' is not a manually added park — parks from the "
                "area search are removed by changing the radius or park count"
            )

    async def _async_handle_delete_photo(call: ServiceCall) -> None:
        place_id = call.data[SERVICE_ATTR_PLACE_ID]
        filename = call.data[SERVICE_ATTR_FILENAME]
        await coordinator.async_remove_photo(place_id, filename)
        await async_delete_photo_files(hass, place_id, [filename])

    if not hass.services.has_service(DOMAIN, SERVICE_RATE_PARK):
        hass.services.async_register(
            DOMAIN, SERVICE_RATE_PARK, _async_handle_rate_park, schema=RATE_PARK_SCHEMA
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_DELETE_REVIEW,
            _async_handle_delete_review,
            schema=DELETE_REVIEW_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_DELETE_PHOTO,
            _async_handle_delete_photo,
            schema=DELETE_PHOTO_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_NEXT_PARK,
            _async_handle_set_next_park,
            schema=SET_NEXT_PARK_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_CLEAR_NEXT_PARK,
            _async_handle_clear_next_park,
            schema=CLEAR_NEXT_PARK_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN, SERVICE_ADD_PARK, _async_handle_add_park, schema=ADD_PARK_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_REMOVE_PARK, _async_handle_remove_park, schema=REMOVE_PARK_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_SET_PARK_TAG, _async_handle_set_park_tag, schema=SET_PARK_TAG_SCHEMA
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_CLEAR_PARK_TAG,
            _async_handle_clear_park_tag,
            schema=CLEAR_PARK_TAG_SCHEMA,
        )

    # Views are global rather than per-entry, and HA raises if the same view
    # name is registered twice (e.g. after a reload), so guard with a flag.
    if not hass.data[DOMAIN].get("_views_registered"):
        async_register_views(hass)
        hass.data[DOMAIN]["_views_registered"] = True

    # Same reasoning as the views above: serving the bundled Lovelace cards
    # from inside custom_components/park_visits (rather than a top-level
    # www/ folder) means HACS updates them with the integration — no manual
    # copy to config/www and no manual "Add Resource" step.
    if not hass.data[DOMAIN].get("_frontend_registered"):
        await async_register_frontend(hass)
        hass.data[DOMAIN]["_frontend_registered"] = True

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options (API key, centre point, radius, count) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        # hass.data[DOMAIN] also holds the _views_registered/_frontend_registered
        # flags, so emptiness can't be used to detect "last entry gone" — count
        # real entries. (Neither views nor the static path/extra JS URL can be
        # unregistered from HA's HTTP app, so the flags deliberately survive a
        # reload.)
        if not any(isinstance(v, dict) and "coordinator" in v for v in hass.data[DOMAIN].values()):
            hass.services.async_remove(DOMAIN, SERVICE_RATE_PARK)
            hass.services.async_remove(DOMAIN, SERVICE_DELETE_REVIEW)
            hass.services.async_remove(DOMAIN, SERVICE_DELETE_PHOTO)
            hass.services.async_remove(DOMAIN, SERVICE_SET_NEXT_PARK)
            hass.services.async_remove(DOMAIN, SERVICE_CLEAR_NEXT_PARK)
            hass.services.async_remove(DOMAIN, SERVICE_ADD_PARK)
            hass.services.async_remove(DOMAIN, SERVICE_REMOVE_PARK)
            hass.services.async_remove(DOMAIN, SERVICE_SET_PARK_TAG)
            hass.services.async_remove(DOMAIN, SERVICE_CLEAR_PARK_TAG)
    return unload_ok
