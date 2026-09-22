"""Just enough Home Assistant for the Park Visits integration to run without it.

The integration is ordinary async Python around the Google Places and Immich
APIs; what ties it to Home Assistant is a thin layer of imports — a storage
helper, an HTTP view base class, a service registry, an update coordinator.
This module provides stand-ins for exactly those, registers them under the
`homeassistant.*` names, and then `custom_components/park_visits` imports and
runs **unmodified**.

That is the whole point: the container ships the same integration source the
Home Assistant install uses, so the two can never drift apart.

Call `install()` before importing anything from the integration.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import aiohttp
import voluptuous as vol

_LOGGER = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# core objects
# --------------------------------------------------------------------------

class HomeAssistantError(Exception):
    """Base error, raised by service handlers to report a usable message."""


class ConfigEntryAuthFailed(HomeAssistantError):
    """Credentials were rejected — here, a bad Google Places API key."""


def callback(func):
    """HA marks sync functions safe to run in the event loop; we needn't care."""
    return func


@dataclass
class ServiceCall:
    """What a service handler receives."""

    data: dict[str, Any]
    domain: str = ""
    service: str = ""


@dataclass
class _Config:
    """`hass.config` — a config directory and the home coordinates."""

    config_dir: str
    latitude: float = 0.0
    longitude: float = 0.0

    def path(self, *parts: str) -> str:
        return os.path.join(self.config_dir, *parts)


class _ServiceRegistry:
    """Collects the services the integration registers, so HTTP can call them."""

    def __init__(self) -> None:
        self._services: dict[str, dict[str, tuple[Callable, Any]]] = {}

    def async_register(self, domain, service, handler, schema=None) -> None:
        self._services.setdefault(domain, {})[service] = (handler, schema)

    def async_remove(self, domain, service) -> None:
        self._services.get(domain, {}).pop(service, None)

    def has_service(self, domain, service) -> bool:
        return service in self._services.get(domain, {})

    def names(self, domain) -> list[str]:
        return sorted(self._services.get(domain, {}))

    async def async_call(self, domain, service, data=None) -> None:
        entry = self._services.get(domain, {}).get(service)
        if entry is None:
            raise HomeAssistantError(f"Unknown service {domain}.{service}")
        handler, schema = entry
        payload = dict(data or {})
        if schema is not None:
            try:
                payload = schema(payload)
            except vol.Invalid as err:
                raise HomeAssistantError(f"Invalid data for {domain}.{service}: {err}") from err
        await handler(ServiceCall(payload, domain, service))


class _HttpRegistry:
    """Collects registered views; the app turns them into aiohttp routes."""

    def __init__(self) -> None:
        self.views: list[Any] = []
        self.static_paths: list[tuple[str, str]] = []

    def register_view(self, view) -> None:
        self.views.append(view)

    def register_static_path(self, url_path, path, cache_headers=True) -> None:
        self.static_paths.append((url_path, path))

    async def async_register_static_paths(self, configs) -> None:
        for cfg in configs:
            self.static_paths.append((cfg.url_path, cfg.path))


@dataclass
class StaticPathConfig:
    url_path: str
    path: str
    cache_headers: bool = True


class _ConfigEntries:
    """Only what the integration asks of it: forward platforms, reload, update."""

    def __init__(self, hass: "HomeAssistant") -> None:
        self._hass = hass
        self.platform_entities: dict[str, list[Any]] = {}

    async def async_forward_entry_setups(self, entry, platforms) -> None:
        import importlib

        for platform in platforms:
            module = importlib.import_module(f"custom_components.park_visits.{platform}")
            collected: list[Any] = []

            def _add(entities, update_before_add=False, _c=collected):
                _c.extend(entities)

            await module.async_setup_entry(self._hass, entry, _add)
            self.platform_entities[platform] = collected

    async def async_unload_platforms(self, entry, platforms) -> bool:
        return True

    async def async_reload(self, entry_id) -> None:
        # The standalone server applies option changes by restarting instead.
        _LOGGER.info("Configuration changed; restart the container to apply it")

    def async_update_entry(self, entry, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(entry, key, value)


class HomeAssistant:
    """The handful of `hass` attributes the integration actually touches."""

    def __init__(self, config_dir: str, latitude: float = 0.0, longitude: float = 0.0) -> None:
        self.data: dict[str, Any] = {}
        self.services = _ServiceRegistry()
        self.http = _HttpRegistry()
        self.config = _Config(config_dir, latitude, longitude)
        self.config_entries = _ConfigEntries(self)
        self.session: aiohttp.ClientSession | None = None
        self.storage_dir = os.path.join(config_dir, ".storage")

    async def async_add_executor_job(self, func, *args):
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)

    def async_create_task(self, coro, name=None):
        return asyncio.get_running_loop().create_task(coro)

    def async_create_background_task(self, coro, name=None):
        return self.async_create_task(coro)


@dataclass
class ConfigEntry:
    """A config entry is just the settings plus an id."""

    entry_id: str
    data: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    title: str = "Park Visits"

    def add_update_listener(self, listener):
        return lambda: None

    def async_on_unload(self, func) -> None:
        return None


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

class Store:
    """HA's storage helper, as one JSON file per key.

    Same contract: `async_load()` returns what was saved (or None), and
    `async_save()` replaces it. Writes go through a temp file and a rename so
    a power cut can't leave a half-written review behind.
    """

    def __init__(self, hass: HomeAssistant, version: int, key: str, **kwargs) -> None:
        self._hass = hass
        self._version = version
        self._path = Path(hass.storage_dir) / key.replace("/", "_")

    async def async_load(self) -> Any:
        def _read():
            if not self._path.exists():
                return None
            try:
                with self._path.open(encoding="utf-8") as handle:
                    return json.load(handle).get("data")
            except (OSError, ValueError) as err:
                _LOGGER.error("Could not read %s: %s", self._path, err)
                return None

        return await self._hass.async_add_executor_job(_read)

    async def async_save(self, data: Any) -> None:
        def _write():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump({"version": self._version, "key": self._path.name, "data": data}, handle)
            os.replace(tmp, self._path)

        await self._hass.async_add_executor_job(_write)

    async def async_remove(self) -> None:
        await self._hass.async_add_executor_job(
            lambda: self._path.unlink(missing_ok=True)
        )


def async_get_clientsession(hass: HomeAssistant) -> aiohttp.ClientSession:
    if hass.session is None or hass.session.closed:
        hass.session = aiohttp.ClientSession()
    return hass.session


class UpdateFailed(HomeAssistantError):
    """Raised by a coordinator when a refresh fails."""


class DataUpdateCoordinator:
    """The subset of HA's coordinator the integration relies on."""

    # HA's is generic — `DataUpdateCoordinator[list[RankedPark]]` must parse.
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, hass, logger, *, name="", update_interval=None, config_entry=None, **kwargs):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.config_entry = config_entry
        self.data: Any = None
        self.last_update_success = True
        self._listeners: list[Callable[[], None]] = []

    async def _async_update_data(self):
        raise NotImplementedError

    async def async_refresh(self) -> None:
        try:
            self.data = await self._async_update_data()
            self.last_update_success = True
        except Exception as err:  # noqa: BLE001 - mirrors HA: record and carry on
            self.last_update_success = False
            self.logger.error("Refresh failed: %s", err)
            raise
        self.async_update_listeners()

    async def async_request_refresh(self) -> None:
        await self.async_refresh()

    async def async_config_entry_first_refresh(self) -> None:
        await self.async_refresh()

    @callback
    def async_set_updated_data(self, data) -> None:
        self.data = data
        self.last_update_success = True
        self.async_update_listeners()

    @callback
    def async_update_listeners(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def async_add_listener(self, update_callback, context=None):
        self._listeners.append(update_callback)

        def _remove():
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return _remove


class _Entity:
    """The entity base: enough for the platforms to describe their state."""

    _attr_name: Any = None
    _attr_unique_id: Any = None
    _attr_should_poll = False
    _attr_extra_state_attributes: dict[str, Any] | None = None
    _attr_icon: Any = None
    _attr_native_value: Any = None
    _attr_attribution: Any = None
    hass: Any = None

    @property
    def name(self):
        return self._attr_name

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def icon(self):
        return self._attr_icon

    @property
    def extra_state_attributes(self):
        return self._attr_extra_state_attributes

    @property
    def available(self) -> bool:
        return True

    def async_write_ha_state(self) -> None:
        return None

    async def async_added_to_hass(self) -> None:
        return None


class CoordinatorEntity(_Entity):
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, coordinator, context=None) -> None:
        self.coordinator = coordinator

    @property
    def available(self) -> bool:
        return getattr(self.coordinator, "last_update_success", True)

    def _handle_coordinator_update(self) -> None:
        return None


class GeolocationEvent(_Entity):
    """geo_location: the state is the distance, plus latitude/longitude."""

    _attr_source: Any = None
    _attr_distance: Any = None
    _attr_latitude: Any = None
    _attr_longitude: Any = None
    _attr_unit_of_measurement: Any = None

    @property
    def source(self):
        return self._attr_source

    @property
    def distance(self):
        return self._attr_distance

    @property
    def latitude(self):
        return self._attr_latitude

    @property
    def longitude(self):
        return self._attr_longitude

    @property
    def state(self):
        return self.distance


class SensorEntity(_Entity):
    _attr_native_unit_of_measurement: Any = None
    _attr_device_class: Any = None
    _attr_state_class: Any = None

    @property
    def native_value(self):
        return self._attr_native_value

    @property
    def state(self):
        return self.native_value


class ButtonEntity(_Entity):
    @property
    def state(self):
        return None

    async def async_press(self) -> None:
        return None


class HomeAssistantView:
    """The view base class: same url/name/requires_auth contract as HA's."""

    url: str = ""
    name: str = ""
    requires_auth: bool = True
    extra_urls: list[str] = []

    @staticmethod
    def json(result, status_code: int = 200, headers=None):
        from aiohttp import web

        return web.json_response(result, status=status_code, headers=headers)

    @staticmethod
    def json_message(message, status_code: int = 200, message_code=None, headers=None):
        from aiohttp import web

        body: dict[str, Any] = {"message": message}
        if message_code is not None:
            body["code"] = message_code
        return web.json_response(body, status=status_code, headers=headers)


def async_at_started(hass, callback_func):
    """Run a callback once the system is up.

    HA's version is synchronous and schedules the callback, so callers don't
    await it — this must behave the same or the callback never runs.
    """
    import inspect

    async def _run():
        result = callback_func(hass)
        if inspect.isawaitable(result):
            await result

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:  # no loop yet — nothing to schedule onto
        pass
    return lambda: None


async def async_get_integration(hass, domain):
    """Only used to locate the integration's bundled www/ directory."""
    root = Path(__file__).resolve().parent.parent / "custom_components" / domain

    class _Integration:
        file_path = root

    return _Integration()


def add_extra_js_url(hass, url, es5=False) -> None:
    """Home Assistant loads dashboard resources; the page does that itself."""
    return None


# --------------------------------------------------------------------------
# config validation (only the two helpers the integration uses)
# --------------------------------------------------------------------------

def _cv_string(value: Any) -> str:
    if value is None:
        raise vol.Invalid("string value is None")
    if isinstance(value, (list, dict)):
        raise vol.Invalid("value should be a string")
    return str(value)


def _cv_has_at_least_one_key(*keys: str):
    def validate(obj):
        if not isinstance(obj, dict):
            raise vol.Invalid("expected dictionary")
        if any(key in obj for key in keys):
            return obj
        raise vol.Invalid(f"must contain at least one of {', '.join(keys)}")

    return validate


# --------------------------------------------------------------------------
# installation
# --------------------------------------------------------------------------

def _module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def install() -> None:
    """Register the stand-ins under `homeassistant.*`. Idempotent."""
    if "homeassistant" in sys.modules:
        return

    ha = _module("homeassistant")
    ha.__path__ = []  # marks it as a package so submodules import cleanly

    _module("homeassistant.core", HomeAssistant=HomeAssistant, ServiceCall=ServiceCall,
            callback=callback, HassJob=object)
    _module("homeassistant.const", CONF_LATITUDE="latitude", CONF_LONGITUDE="longitude",
            CONF_NAME="name", CONF_API_KEY="api_key", Platform=object,
            UnitOfLength=types.SimpleNamespace(KILOMETERS="km"))
    _module("homeassistant.exceptions", HomeAssistantError=HomeAssistantError,
            ConfigEntryAuthFailed=ConfigEntryAuthFailed,
            ConfigEntryNotReady=HomeAssistantError)
    config_entries = _module(
        "homeassistant.config_entries",
        ConfigEntry=ConfigEntry,
        ConfigFlow=object,
        OptionsFlow=object,
        OptionsFlowWithConfigEntry=object,
        SOURCE_USER="user",
    )
    ha.config_entries = config_entries

    components = _module("homeassistant.components")
    components.__path__ = []
    _module("homeassistant.components.http", HomeAssistantView=HomeAssistantView,
            StaticPathConfig=StaticPathConfig)
    _module("homeassistant.components.geo_location", GeolocationEvent=GeolocationEvent)
    _module("homeassistant.components.sensor", SensorEntity=SensorEntity,
            SensorDeviceClass=object, SensorStateClass=object)
    _module("homeassistant.components.button", ButtonEntity=ButtonEntity)
    _module("homeassistant.components.frontend", add_extra_js_url=add_extra_js_url)

    helpers = _module("homeassistant.helpers")
    helpers.__path__ = []
    _module("homeassistant.helpers.storage", Store=Store)
    _module("homeassistant.helpers.aiohttp_client",
            async_get_clientsession=async_get_clientsession)
    _module("homeassistant.helpers.update_coordinator",
            DataUpdateCoordinator=DataUpdateCoordinator, UpdateFailed=UpdateFailed,
            CoordinatorEntity=CoordinatorEntity)
    _module("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
    _module("homeassistant.helpers.entity", Entity=_Entity)
    _module("homeassistant.helpers.start", async_at_started=async_at_started)
    _module("homeassistant.helpers.config_validation",
            string=_cv_string, has_at_least_one_key=_cv_has_at_least_one_key,
            positive_int=int, boolean=bool)
    _module("homeassistant.helpers.selector", selector=lambda cfg: cfg)
    _module("homeassistant.loader", async_get_integration=async_get_integration)
    _module("homeassistant.util", slugify=lambda value: value)
