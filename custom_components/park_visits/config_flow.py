"""Config flow for Park Visits."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import callback

from .const import (
    CONF_API_KEY,
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

# Deliberately plain voluptuous validators rather than HA Selectors: a
# NumberSelector-based version of this schema made the config_entries flow
# REST endpoint reject the request with a bare 400 before the flow even
# initialized (selector JSON-schema serialization issue). Plain validators
# render as ordinary form fields and are known to work.


def _schema(defaults: dict[str, Any], *, require_key: bool) -> vol.Schema:
    key_validator = vol.Required(CONF_API_KEY) if require_key else vol.Optional(
        CONF_API_KEY, default=defaults.get(CONF_API_KEY, "")
    )
    return vol.Schema(
        {
            key_validator: str,
            vol.Required(CONF_LATITUDE, default=defaults[CONF_LATITUDE]): vol.Coerce(float),
            vol.Required(CONF_LONGITUDE, default=defaults[CONF_LONGITUDE]): vol.Coerce(float),
            vol.Required(CONF_RADIUS_KM, default=defaults[CONF_RADIUS_KM]): vol.All(
                vol.Coerce(float), vol.Range(min=MIN_RADIUS_KM, max=MAX_RADIUS_KM)
            ),
            vol.Required(CONF_MAX_PARKS, default=defaults[CONF_MAX_PARKS]): vol.All(
                vol.Coerce(int), vol.Range(min=MIN_MAX_PARKS, max=MAX_MAX_PARKS)
            ),
        }
    )


class ParkVisitsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Park Visits."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """First (and only) setup step: Google API key, centre point, radius and count."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_API_KEY].strip():
                errors[CONF_API_KEY] = "api_key_required"
            else:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=DEFAULT_NAME, data={}, options=user_input)

        defaults = {
            CONF_LATITUDE: DEFAULT_LATITUDE,
            CONF_LONGITUDE: DEFAULT_LONGITUDE,
            CONF_RADIUS_KM: DEFAULT_RADIUS_KM,
            CONF_MAX_PARKS: DEFAULT_MAX_PARKS,
        }
        return self.async_show_form(
            step_id="user", data_schema=_schema(defaults, require_key=True), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ParkVisitsOptionsFlow:
        """Get the options flow for this handler."""
        return ParkVisitsOptionsFlow(config_entry)


class ParkVisitsOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Park Visits (change API key, centre point, radius, count)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_API_KEY].strip():
                errors[CONF_API_KEY] = "api_key_required"
            else:
                return self.async_create_entry(title="", data=user_input)

        defaults = {
            CONF_API_KEY: self.config_entry.options.get(CONF_API_KEY, ""),
            CONF_LATITUDE: self.config_entry.options.get(CONF_LATITUDE, DEFAULT_LATITUDE),
            CONF_LONGITUDE: self.config_entry.options.get(CONF_LONGITUDE, DEFAULT_LONGITUDE),
            CONF_RADIUS_KM: self.config_entry.options.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM),
            CONF_MAX_PARKS: self.config_entry.options.get(CONF_MAX_PARKS, DEFAULT_MAX_PARKS),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(defaults, require_key=False),
            errors=errors,
        )
