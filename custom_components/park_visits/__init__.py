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
    DOMAIN,
    MAX_OUR_RATING,
    MIN_OUR_RATING,
    SERVICE_ATTR_NOTE,
    SERVICE_ATTR_PLACE_ID,
    SERVICE_ATTR_RATING,
    SERVICE_RATE_PARK,
)
from .coordinator import ParkVisitsCoordinator
from .storage import ParkReviewStore

PLATFORMS = ["geo_location", "sensor"]

RATE_PARK_SCHEMA = vol.Schema(
    {
        vol.Required(SERVICE_ATTR_PLACE_ID): cv.string,
        vol.Required(SERVICE_ATTR_RATING): vol.All(
            vol.Coerce(float), vol.Range(min=MIN_OUR_RATING, max=MAX_OUR_RATING)
        ),
        vol.Optional(SERVICE_ATTR_NOTE, default=""): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Park Visits from a config entry."""
    reviews = ParkReviewStore(hass, entry.entry_id)
    await reviews.async_load()

    coordinator = ParkVisitsCoordinator(hass, entry, reviews)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "reviews": reviews,
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
            place_id, call.data[SERVICE_ATTR_RATING], call.data[SERVICE_ATTR_NOTE]
        )

    if not hass.services.has_service(DOMAIN, SERVICE_RATE_PARK):
        hass.services.async_register(
            DOMAIN, SERVICE_RATE_PARK, _async_handle_rate_park, schema=RATE_PARK_SCHEMA
        )

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options (API key, centre point, radius, count) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_RATE_PARK)
    return unload_ok
