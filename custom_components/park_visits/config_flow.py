"""Config flow for Park Visits."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_MAX_PARKS,
    CONF_RADIUS_KM,
    DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE,
    DEFAULT_MAX_PARKS,
    DEFAULT_NAME,
    DEFAULT_RADIUS_KM,
    DOMAIN,
    MAX_MAX_PARKS,
    MAX_RADIUS_KM,
    MIN_MAX_PARKS,
    MIN_RADIUS_KM,
)


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_LATITUDE, default=defaults[CONF_LATITUDE]): NumberSelector(
                NumberSelectorConfig(min=-90, max=90, step=0.0001, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_LONGITUDE, default=defaults[CONF_LONGITUDE]): NumberSelector(
                NumberSelectorConfig(min=-180, max=180, step=0.0001, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_RADIUS_KM, default=defaults[CONF_RADIUS_KM]): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_RADIUS_KM, max=MAX_RADIUS_KM, step=1, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(CONF_MAX_PARKS, default=defaults[CONF_MAX_PARKS]): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_MAX_PARKS, max=MAX_MAX_PARKS, step=1, mode=NumberSelectorMode.BOX
                )
            ),
        }
    )


class ParkVisitsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Park Visits."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """First (and only) setup step: pick the centre point, radius and count."""
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=DEFAULT_NAME, data={}, options=user_input)

        defaults = {
            CONF_LATITUDE: DEFAULT_LATITUDE,
            CONF_LONGITUDE: DEFAULT_LONGITUDE,
            CONF_RADIUS_KM: DEFAULT_RADIUS_KM,
            CONF_MAX_PARKS: DEFAULT_MAX_PARKS,
        }
        return self.async_show_form(step_id="user", data_schema=_schema(defaults))

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ParkVisitsOptionsFlow:
        """Get the options flow for this handler."""
        return ParkVisitsOptionsFlow(config_entry)


class ParkVisitsOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Park Visits (change centre point, radius, count)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        defaults = {
            CONF_LATITUDE: self.config_entry.options.get(CONF_LATITUDE, DEFAULT_LATITUDE),
            CONF_LONGITUDE: self.config_entry.options.get(CONF_LONGITUDE, DEFAULT_LONGITUDE),
            CONF_RADIUS_KM: self.config_entry.options.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM),
            CONF_MAX_PARKS: self.config_entry.options.get(CONF_MAX_PARKS, DEFAULT_MAX_PARKS),
        }
        return self.async_show_form(step_id="init", data_schema=_schema(defaults))
