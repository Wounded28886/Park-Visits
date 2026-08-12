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

from .const import ATTRIBUTION, CONF_MAX_PARKS, CONF_RADIUS_KM, DOMAIN
from .coordinator import ParkVisitsCoordinator

ICON = "mdi:pine-tree"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the summary sensor."""
    coordinator: ParkVisitsCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ParkCountSensor(coordinator, entry)])


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
            CONF_LATITUDE: options.get(CONF_LATITUDE),
            CONF_LONGITUDE: options.get(CONF_LONGITUDE),
            CONF_RADIUS_KM: options.get(CONF_RADIUS_KM),
            CONF_MAX_PARKS: options.get(CONF_MAX_PARKS),
        }
