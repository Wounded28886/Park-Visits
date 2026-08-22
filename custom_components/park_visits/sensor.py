"""Sensor platform for Park Visits — a small summary sensor.

Per-park detail lives on each geo_location entity, not here, so this
entity's attributes stay small (the recorder warns about large attribute
payloads, and a 100-park attribute blob would be one).
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ROLE,
    ATTR_SET_AT,
    ATTRIBUTION,
    CONF_LOCATION_NAME,
    CONF_MAX_PARKS,
    CONF_PEOPLE,
    CONF_RADIUS_KM,
    DEFAULT_PEOPLE,
    DOMAIN,
    ROLE_LAST_VISITED,
    ROLE_NEXT_PARK,
    ROLE_PARK_COUNT,
)
from .coordinator import ParkVisitsCoordinator

ICON = "mdi:pine-tree"
ICON_NEXT = "mdi:map-marker-right"
ICON_LAST = "mdi:history"
ICON_VISITED = "mdi:map-check"

NONE_SELECTED = "None selected"
NONE_VISITED = "No visits yet"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the summary sensors."""
    coordinator: ParkVisitsCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [
            ParkCountSensor(coordinator, entry),
            NextParkSensor(coordinator, entry),
            LastVisitedParkSensor(coordinator, entry),
            VisitedCountSensor(coordinator, entry),
        ]
    )


class ParkCountSensor(CoordinatorEntity[ParkVisitsCoordinator], SensorEntity):
    """Reports how many parks are currently in range and tracked."""

    _attr_attribution = ATTRIBUTION
    _attr_icon = ICON
    _attr_native_unit_of_measurement = "parks"
    _attr_name = "Nearby Parks"

    def __init__(self, coordinator: ParkVisitsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_count"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        options = self._entry.options
        return {
            # Cards read the configured people list from here (by role, not
            # entity_id) to build one rating column/field per person.
            ATTR_ROLE: ROLE_PARK_COUNT,
            CONF_LOCATION_NAME: options.get(CONF_LOCATION_NAME),
            CONF_LATITUDE: options.get(CONF_LATITUDE),
            CONF_LONGITUDE: options.get(CONF_LONGITUDE),
            CONF_RADIUS_KM: options.get(CONF_RADIUS_KM),
            CONF_MAX_PARKS: options.get(CONF_MAX_PARKS),
            CONF_PEOPLE: options.get(CONF_PEOPLE, DEFAULT_PEOPLE),
        }


class NextParkSensor(CoordinatorEntity[ParkVisitsCoordinator], SensorEntity):
    """The park we've decided to visit next."""

    _attr_attribution = ATTRIBUTION
    _attr_icon = ICON_NEXT
    _attr_name = "Next park"

    def __init__(self, coordinator: ParkVisitsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_next_park"

    @property
    def native_value(self) -> str:
        planned = self.coordinator.next_park()
        return (planned.get("park_name") or "Unknown park") if planned else NONE_SELECTED

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        planned = self.coordinator.next_park() or {}
        return {
            # Cards find this sensor by role, since entity_ids can be renamed.
            ATTR_ROLE: ROLE_NEXT_PARK,
            "place_id": planned.get("place_id"),
            "rating": planned.get("rating"),
            "rating_count": planned.get("rating_count"),
            "distance_km": planned.get("distance_km"),
            "categories": planned.get("categories") or [],
            "address": planned.get("address", ""),
            "still_tracked": planned.get("still_tracked"),
            ATTR_SET_AT: planned.get(ATTR_SET_AT),
        }


class LastVisitedParkSensor(CoordinatorEntity[ParkVisitsCoordinator], SensorEntity):
    """The most recently reviewed park — our record of the last visit."""

    _attr_attribution = ATTRIBUTION
    _attr_icon = ICON_LAST
    _attr_name = "Last visited park"

    def __init__(self, coordinator: ParkVisitsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_last_visited"

    @property
    def native_value(self) -> str:
        visited = self.coordinator.last_visited()
        return (visited.get("park_name") or "Unknown park") if visited else NONE_VISITED

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        visited = self.coordinator.last_visited() or {}
        return {
            ATTR_ROLE: ROLE_LAST_VISITED,
            "place_id": visited.get("place_id"),
            "our_overall_rating": visited.get("our_overall_rating"),
            "our_person_ratings": visited.get("our_person_ratings", {}),
            "our_liked": visited.get("our_liked", ""),
            "our_disliked": visited.get("our_disliked", ""),
            "our_note": visited.get("our_note", ""),
            "our_photo_count": visited.get("our_photo_count", 0),
            "visit_date": visited.get("visit_date"),
            "rating": visited.get("rating"),
            "distance_km": visited.get("distance_km"),
            "still_tracked": visited.get("still_tracked"),
        }


class VisitedCountSensor(CoordinatorEntity[ParkVisitsCoordinator], SensorEntity):
    """How many of the currently tracked parks we've actually visited.

    "Visited" means a review with a visit date was submitted (a stub
    review created purely by an early photo upload doesn't count — same
    rule the table card uses to decide "Review" vs "Edit").
    """

    _attr_attribution = ATTRIBUTION
    _attr_icon = ICON_VISITED
    _attr_native_unit_of_measurement = "parks"
    _attr_name = "Parks Visited"

    def __init__(self, coordinator: ParkVisitsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_visited_count"

    @property
    def native_value(self) -> int:
        return sum(1 for p in self.coordinator.data if p.our_visit_date)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        total = len(self.coordinator.data)
        visited = self.native_value
        return {
            "total": total,
            "percent": round((visited / total) * 100, 1) if total else 0,
        }
