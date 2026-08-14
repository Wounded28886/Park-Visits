"""Config flow for Park Visits."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import callback

from .const import (
    CONF_API_KEY,
    CONF_LOCATION,
    CONF_LOCATION_NAME,
    CONF_MAX_PARKS,
    CONF_RADIUS_KM,
    DEFAULT_MAX_PARKS,
    DEFAULT_NAME,
    DEFAULT_RADIUS_KM,
    DOMAIN,
    MAX_MAX_PARKS,
    MAX_RADIUS_KM,
    MIN_MAX_PARKS,
    MIN_RADIUS_KM,
)
from .geocoding import (
    GeocodeAuthFailed,
    GeocodeConnectionError,
    GeocodeNotFound,
    async_geocode_location,
)

_LOGGER = logging.getLogger(__name__)

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
            vol.Required(CONF_LOCATION, default=defaults.get(CONF_LOCATION, "")): str,
            vol.Required(CONF_RADIUS_KM, default=defaults[CONF_RADIUS_KM]): vol.All(
                vol.Coerce(float), vol.Range(min=MIN_RADIUS_KM, max=MAX_RADIUS_KM)
            ),
            vol.Required(CONF_MAX_PARKS, default=defaults[CONF_MAX_PARKS]): vol.All(
                vol.Coerce(int), vol.Range(min=MIN_MAX_PARKS, max=MAX_MAX_PARKS)
            ),
        }
    )


# Maps a geocoding failure to the form field its error should be shown
# against ("base" is HA's convention for a whole-form error banner).
_GEOCODE_ERROR_FIELD = {
    "invalid_api_key": CONF_API_KEY,
    "location_not_found": CONF_LOCATION,
    "cannot_connect": "base",
}


async def _async_resolve_location(
    hass: Any, api_key: str, query: str
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """Geocode `query`. Returns (options update, errors)."""
    try:
        result = await async_geocode_location(hass, api_key, query)
    except GeocodeAuthFailed:
        return None, {_GEOCODE_ERROR_FIELD["invalid_api_key"]: "invalid_api_key"}
    except GeocodeNotFound:
        return None, {_GEOCODE_ERROR_FIELD["location_not_found"]: "location_not_found"}
    except GeocodeConnectionError:
        _LOGGER.warning("Could not reach Google to resolve location %r", query, exc_info=True)
        return None, {_GEOCODE_ERROR_FIELD["cannot_connect"]: "cannot_connect"}
    return (
        {
            CONF_LATITUDE: result.latitude,
            CONF_LONGITUDE: result.longitude,
            CONF_LOCATION_NAME: result.formatted_address,
        },
        {},
    )


class ParkVisitsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Park Visits."""

    VERSION = 3

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """First (and only) setup step: Google API key, a place to search around, radius and count."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_API_KEY].strip():
                errors[CONF_API_KEY] = "api_key_required"
            elif not user_input[CONF_LOCATION].strip():
                errors[CONF_LOCATION] = "location_required"
            else:
                resolved, errors = await _async_resolve_location(
                    self.hass, user_input[CONF_API_KEY], user_input[CONF_LOCATION]
                )
                if resolved:
                    await self.async_set_unique_id(DOMAIN)
                    self._abort_if_unique_id_configured()
                    options = {**user_input, **resolved}
                    title = f"{DEFAULT_NAME} — {resolved[CONF_LOCATION_NAME]}"
                    return self.async_create_entry(title=title, data={}, options=options)

        defaults = {
            CONF_LOCATION: (user_input or {}).get(CONF_LOCATION, ""),
            CONF_RADIUS_KM: (user_input or {}).get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM),
            CONF_MAX_PARKS: (user_input or {}).get(CONF_MAX_PARKS, DEFAULT_MAX_PARKS),
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
        return ParkVisitsOptionsFlow()


class ParkVisitsOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Park Visits (change API key, location, radius, count).

    Deliberately no __init__ override: recent Home Assistant versions inject
    self.config_entry automatically and raise if a subclass assigns it
    manually. The old `def __init__(self, config_entry): self.config_entry =
    config_entry` pattern (still shown in a lot of older tutorials) broke
    this silently — every attempt to read this entry's options raised here.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_API_KEY].strip():
                errors[CONF_API_KEY] = "api_key_required"
            elif not user_input[CONF_LOCATION].strip():
                errors[CONF_LOCATION] = "location_required"
            else:
                resolved, errors = await _async_resolve_location(
                    self.hass, user_input[CONF_API_KEY], user_input[CONF_LOCATION]
                )
                if resolved:
                    options = {**user_input, **resolved}
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        title=f"{DEFAULT_NAME} — {resolved[CONF_LOCATION_NAME]}",
                    )
                    return self.async_create_entry(title="", data=options)

        defaults = {
            CONF_API_KEY: self.config_entry.options.get(CONF_API_KEY, ""),
            CONF_LOCATION: self.config_entry.options.get(CONF_LOCATION, ""),
            CONF_RADIUS_KM: self.config_entry.options.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM),
            CONF_MAX_PARKS: self.config_entry.options.get(CONF_MAX_PARKS, DEFAULT_MAX_PARKS),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(defaults, require_key=False),
            errors=errors,
        )
