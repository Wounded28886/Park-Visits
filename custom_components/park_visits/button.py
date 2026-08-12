"""Button platform for Park Visits — manual "fetch from Google" trigger.

The coordinator has no polling timer (see coordinator.py), so pressing this
button is the only thing (besides initial setup or an options change) that
spends Places API quota.
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ATTRIBUTION, DOMAIN
from .coordinator import ParkVisitsCoordinator

ICON = "mdi:refresh"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the manual refresh button."""
    coordinator: ParkVisitsCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([ParkVisitsRefreshButton(coordinator, entry)])


class ParkVisitsRefreshButton(ButtonEntity):
    """Fetches parks from Google Places on demand."""

    _attr_attribution = ATTRIBUTION
    _attr_icon = ICON
    _attr_name = "Refresh parks"
    _attr_has_entity_name = False

    def __init__(self, coordinator: ParkVisitsCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_refresh"

    async def async_press(self) -> None:
        """Trigger a coordinator refresh (a real Google Places API call)."""
        await self._coordinator.async_request_refresh()
