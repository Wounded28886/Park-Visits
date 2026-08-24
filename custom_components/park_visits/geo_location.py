"""Geolocation platform for Park Visits — one marker per park for the Map card."""
from __future__ import annotations

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ADDRESS,
    ATTR_CATEGORIES,
    ATTR_GOOGLE_MAPS_URI,
    ATTR_OUR_DISLIKED,
    ATTR_OUR_FACILITIES_RATING,
    ATTR_OUR_LIKED,
    ATTR_OUR_NOTE,
    ATTR_OUR_OVERALL_RATING,
    ATTR_OUR_PARKING_RATING,
    ATTR_OUR_PERSON_RATINGS,
    ATTR_OUR_PHOTO_COUNT,
    ATTR_OUR_PLAYGROUND_RATING,
    ATTR_OUR_SCENERY_RATING,
    ATTR_OUR_VISIT_DATE,
    ATTR_OUR_WILDLIFE_RATING,
    ATTR_PLACE_ID,
    ATTR_MANUALLY_ADDED,
    ATTR_RANK,
    ATTR_RATING,
    ATTR_RATING_COUNT,
    ATTRIBUTION,
    DOMAIN,
    SOURCE,
)
from .coordinator import ParkVisitsCoordinator, RankedPark

ICON = "mdi:tree"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up one geo_location entity per tracked park.

    A manual refresh can bring in parks that weren't part of the previous
    fetch (a new top-N entrant after a rating change, say), so new entities
    are added as they show up in later coordinator updates too — not just
    once at startup. Parks that drop out of the current list keep their
    entity (it just goes unavailable) rather than being removed, so their
    history/logbook isn't lost.
    """
    coordinator: ParkVisitsCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    known_ids: set[str] = set()

    def _add_new_entities() -> None:
        new_parks = [park for park in coordinator.data if park.unique_id not in known_ids]
        if new_parks:
            known_ids.update(park.unique_id for park in new_parks)
            async_add_entities(ParkGeolocationEvent(coordinator, park) for park in new_parks)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


class ParkGeolocationEvent(CoordinatorEntity[ParkVisitsCoordinator], GeolocationEvent):
    """A single park pinned on the map."""

    _attr_attribution = ATTRIBUTION
    _attr_icon = ICON
    _attr_source = SOURCE
    _attr_unit_of_measurement = "km"
    _attr_should_poll = False

    def __init__(self, coordinator: ParkVisitsCoordinator, park: RankedPark) -> None:
        super().__init__(coordinator)
        self._park_id = park.unique_id
        self._attr_unique_id = f"{DOMAIN}_{park.unique_id}"
        self._attr_name = park.name

    @property
    def _park(self) -> RankedPark | None:
        for park in self.coordinator.data:
            if park.unique_id == self._park_id:
                return park
        return None

    @property
    def available(self) -> bool:
        return super().available and self._park is not None

    @property
    def latitude(self) -> float | None:
        park = self._park
        return park.latitude if park else None

    @property
    def longitude(self) -> float | None:
        park = self._park
        return park.longitude if park else None

    @property
    def distance(self) -> float | None:
        park = self._park
        return park.distance_km if park else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        park = self._park
        if not park:
            return {}
        return {
            ATTR_RANK: park.rank,
            ATTR_PLACE_ID: park.place_id,
            ATTR_CATEGORIES: park.categories,
            ATTR_ADDRESS: park.address,
            ATTR_RATING: park.rating,
            ATTR_RATING_COUNT: park.rating_count,
            ATTR_GOOGLE_MAPS_URI: park.google_maps_uri,
            ATTR_OUR_OVERALL_RATING: park.our_overall_rating,
            ATTR_OUR_PERSON_RATINGS: park.our_person_ratings,
            ATTR_OUR_PLAYGROUND_RATING: park.our_playground_rating,
            ATTR_OUR_SCENERY_RATING: park.our_scenery_rating,
            ATTR_OUR_WILDLIFE_RATING: park.our_wildlife_rating,
            ATTR_OUR_FACILITIES_RATING: park.our_facilities_rating,
            ATTR_OUR_PARKING_RATING: park.our_parking_rating,
            ATTR_OUR_NOTE: park.our_note,
            ATTR_OUR_LIKED: park.our_liked,
            ATTR_OUR_DISLIKED: park.our_disliked,
            ATTR_OUR_PHOTO_COUNT: park.our_photo_count,
            ATTR_OUR_VISIT_DATE: park.our_visit_date,
            # Lets the card badge it and offer to remove it again.
            ATTR_MANUALLY_ADDED: park.manually_added,
        }
