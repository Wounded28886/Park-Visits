"""Geolocation platform for Park Visits — one marker per park for the Map card."""
from __future__ import annotations

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_CATEGORY, ATTR_DESCRIPTION, ATTR_LOCALITY, ATTR_RANK, ATTRIBUTION, DOMAIN, SOURCE
from .coordinator import ParkVisitsCoordinator, RankedPark

ICON = "mdi:tree"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up one geo_location entity per tracked park."""
    coordinator: ParkVisitsCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(ParkGeolocationEvent(coordinator, park) for park in coordinator.data)


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
            ATTR_CATEGORY: park.category,
            ATTR_LOCALITY: park.locality,
            ATTR_DESCRIPTION: park.description,
        }
