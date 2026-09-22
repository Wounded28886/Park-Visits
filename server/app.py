#!/usr/bin/env python3
"""Park Visits, standalone — the same integration, without Home Assistant.

Runs the unmodified `custom_components/park_visits` code on top of the
stand-ins in ha_compat, and puts an aiohttp server in front of it:

  * the integration's own HTTP views, mounted at the same paths the cards
    already call (/api/park_visits/...),
  * its services, exposed as POST /api/services/park_visits/<service>,
  * its entities, served as /api/states in the shape a dashboard card expects,
  * the two cards themselves, plus a page that stands in for the dashboard.

Everything is stored in DATA_DIR: parks, reviews, photos and settings.

Environment:
  GOOGLE_API_KEY     (required)  Google Places API key
  LOCATION           (required on first run)  e.g. "Brisbane, Australia"
  LATITUDE/LONGITUDE (optional)  skip the lookup by giving coordinates
  RADIUS_KM          (25)        how far out to search
  MAX_PARKS          (60)        how many parks to track
  PEOPLE             (Kids,Mum,Dad)  comma-separated rater names
  IMMICH_URL         (optional)  Immich server, for photos by tag
  IMMICH_API_KEY     (optional)
  IMMICH_MAX_ASSETS  (200)
  TITLE              (Park Visits)
  PORT               (8098)
  DATA_DIR           (/data)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import ha_compat  # noqa: E402

ha_compat.install()

import aiohttp  # noqa: E402
from aiohttp import web  # noqa: E402

from custom_components.park_visits import async_setup_entry  # noqa: E402
from custom_components.park_visits.const import (  # noqa: E402
    CONF_API_KEY,
    CONF_IMMICH_API_KEY,
    CONF_IMMICH_MAX_ASSETS,
    CONF_IMMICH_URL,
    CONF_LOCATION_NAME,
    CONF_MAX_PARKS,
    CONF_PEOPLE,
    CONF_RADIUS_KM,
    DOMAIN,
    SOURCE,
)
from custom_components.park_visits.geocoding import (  # noqa: E402
    GeocodeError,
    async_search_places,
)

_LOGGER = logging.getLogger("park_visits.server")

PORT = int(os.environ.get("PORT", 8098))
DATA_DIR = os.environ.get("DATA_DIR", "/data")
TITLE = os.environ.get("TITLE", "Park Visits")
ENTRY_ID = "standalone"
SETTINGS_FILE = Path(DATA_DIR) / "settings.json"


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return slug or "unknown"


async def _resolve_location(hass, api_key: str, query: str) -> tuple[str, float, float]:
    """Turn a place name into coordinates, the way the config flow does."""
    results = await async_search_places(hass, api_key, query)
    if not results:
        raise RuntimeError(f"Could not find anywhere called {query!r}")
    top = results[0]
    return top["name"], top["latitude"], top["longitude"]


async def build_options(hass) -> dict:
    """Settings from the environment, with the resolved location cached.

    Looking a location up costs a Places call, so the answer is written to
    settings.json and reused on every later start.
    """
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "GOOGLE_API_KEY is not set — Park Visits needs a Google Places API key. "
            "See server/README.md."
        )

    saved: dict = {}
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except ValueError:
            _LOGGER.warning("settings.json unreadable; looking the location up again")

    location = os.environ.get("LOCATION", "").strip()
    latitude, longitude = _env_float("LATITUDE"), _env_float("LONGITUDE")
    name = location or saved.get(CONF_LOCATION_NAME, "")

    if latitude is None or longitude is None:
        # Reuse the cached answer unless the configured location changed.
        if saved.get("location_query") == location and saved.get("latitude") is not None:
            latitude, longitude = saved["latitude"], saved["longitude"]
            name = saved.get(CONF_LOCATION_NAME, location)
        elif location:
            _LOGGER.info("Looking up %s", location)
            name, latitude, longitude = await _resolve_location(hass, api_key, location)
            _LOGGER.info("Using %s (%.4f, %.4f)", name, latitude, longitude)
        else:
            raise SystemExit(
                "Set LOCATION (e.g. \"Brisbane, Australia\"), or LATITUDE and LONGITUDE."
            )
    if not name:
        # Coordinates given directly — label the area with them.
        name = f"{latitude:.4f}, {longitude:.4f}"

    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps({
        "location_query": location,
        CONF_LOCATION_NAME: name,
        "latitude": latitude,
        "longitude": longitude,
    }, indent=2), encoding="utf-8")

    people = [p.strip() for p in os.environ.get("PEOPLE", "Kids,Mum,Dad").split(",") if p.strip()]
    return {
        CONF_API_KEY: api_key,
        CONF_LOCATION_NAME: name,
        "latitude": latitude,
        "longitude": longitude,
        CONF_RADIUS_KM: int(os.environ.get("RADIUS_KM", 25)),
        CONF_MAX_PARKS: int(os.environ.get("MAX_PARKS", 60)),
        CONF_PEOPLE: people,
        CONF_IMMICH_URL: os.environ.get("IMMICH_URL", "").strip(),
        CONF_IMMICH_API_KEY: os.environ.get("IMMICH_API_KEY", "").strip(),
        CONF_IMMICH_MAX_ASSETS: int(os.environ.get("IMMICH_MAX_ASSETS", 200)),
    }


def entity_states(hass) -> list[dict]:
    """The integration's entities, in the shape a dashboard card expects.

    The entity objects are the integration's own, so their attributes are
    whatever Home Assistant would show — no second implementation to drift.
    """
    states: list[dict] = []
    used: set[str] = set()
    for platform, entities in hass.config_entries.platform_entities.items():
        for entity in entities:
            slug = _slugify(entity.name or entity.unique_id or "entity")
            entity_id = f"{platform}.{slug}"
            suffix = 2
            while entity_id in used:
                entity_id = f"{platform}.{slug}_{suffix}"
                suffix += 1
            used.add(entity_id)

            attributes = dict(entity.extra_state_attributes or {})
            attributes["friendly_name"] = entity.name
            if getattr(entity, "_attr_attribution", None):
                attributes["attribution"] = entity._attr_attribution
            if entity.icon:
                attributes["icon"] = entity.icon
            if platform == "geo_location":
                attributes["source"] = getattr(entity, "source", SOURCE)
                attributes["latitude"] = entity.latitude
                attributes["longitude"] = entity.longitude
                attributes["unit_of_measurement"] = "km"
            elif platform == "sensor":
                unit = getattr(entity, "_attr_native_unit_of_measurement", None)
                if unit:
                    attributes["unit_of_measurement"] = unit

            try:
                value = entity.state
            except Exception as err:  # noqa: BLE001 - a broken entity must not break the page
                _LOGGER.debug("Entity %s has no state: %s", entity_id, err)
                value = None
            if not entity.available:
                value = "unavailable"

            states.append({
                "entity_id": entity_id,
                "state": "unknown" if value is None else value,
                "attributes": attributes,
            })
    return states


def mount_views(app: web.Application, hass) -> None:
    """Expose the integration's own views at the paths the cards already use."""
    for view in hass.http.views:
        for method in ("get", "post", "put", "delete"):
            handler = getattr(view, method, None)
            if handler is None:
                continue

            async def route(request, _handler=handler):
                return await _handler(request, **request.match_info)

            for url in [view.url, *getattr(view, "extra_urls", [])]:
                app.router.add_route(method.upper(), url, route)
                _LOGGER.debug("mounted %s %s", method.upper(), url)


@web.middleware
async def errors_as_json(request, handler):
    """Report failures as JSON so the cards can show them."""
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except ha_compat.HomeAssistantError as err:
        return web.json_response({"message": str(err)}, status=400)
    except Exception as err:  # noqa: BLE001
        _LOGGER.exception("Unhandled error on %s", request.path)
        return web.json_response({"message": str(err)}, status=500)


async def create_app() -> web.Application:
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    hass = ha_compat.HomeAssistant(DATA_DIR)
    options = await build_options(hass)
    hass.config.latitude = options["latitude"]
    hass.config.longitude = options["longitude"]

    entry = ha_compat.ConfigEntry(entry_id=ENTRY_ID, options=options, title=TITLE)
    _LOGGER.info("Setting up Park Visits for %s", options[CONF_LOCATION_NAME])
    await async_setup_entry(hass, entry)

    store = hass.data[DOMAIN][ENTRY_ID]
    coordinator = store["coordinator"]
    _LOGGER.info("Tracking %d parks", len(coordinator.data or []))

    app = web.Application(middlewares=[errors_as_json], client_max_size=32 * 1024 * 1024)
    app["hass"] = hass
    app["entry"] = entry
    app["coordinator"] = coordinator

    mount_views(app, hass)

    async def config_view(request):
        return web.json_response({
            "title": TITLE,
            "location": options[CONF_LOCATION_NAME],
            "people": options[CONF_PEOPLE],
            "radius_km": options[CONF_RADIUS_KM],
            "max_parks": options[CONF_MAX_PARKS],
            "immich": bool(options[CONF_IMMICH_URL] and options[CONF_IMMICH_API_KEY]),
            "services": hass.services.names(DOMAIN),
        })

    async def states_view(request):
        return web.json_response(entity_states(hass))

    async def service_view(request):
        service = request.match_info["service"]
        try:
            payload = await request.json() if request.can_read_body else {}
        except ValueError:
            payload = {}
        await hass.services.async_call(DOMAIN, service, payload)
        return web.json_response({"ok": True, "states": entity_states(hass)})

    async def refresh_view(request):
        """What the integration's refresh button does — a real Places call."""
        await coordinator.async_request_refresh()
        return web.json_response({"ok": True, "parks": len(coordinator.data or [])})

    async def health_view(request):
        return web.json_response({
            "ok": True,
            "parks": len(coordinator.data or []),
            "location": options[CONF_LOCATION_NAME],
            "immich": bool(options[CONF_IMMICH_URL]),
        })

    app.router.add_get("/api/config", config_view)
    app.router.add_get("/api/states", states_view)
    app.router.add_post("/api/services/park_visits/{service}", service_view)
    app.router.add_post("/api/refresh", refresh_view)
    app.router.add_get("/healthz", health_view)

    # The cards, served from the integration's own www/ directory.
    cards = ROOT / "custom_components" / DOMAIN / "www"
    app.router.add_static("/cards/", cards)

    public = HERE / "public"

    async def index(request):
        return web.FileResponse(public / "index.html")

    app.router.add_get("/", index)
    app.router.add_static("/static/", public)

    async def _close_session(_app):
        if hass.session and not hass.session.closed:
            await hass.session.close()

    app.on_cleanup.append(_close_session)
    return app


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Setup does real I/O (loading storage, maybe a Places call), and the
    # sessions it opens must belong to the loop that will serve requests —
    # so build the app on the loop run_app is going to use.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = loop.run_until_complete(create_app())
    _LOGGER.info("Park Visits listening on http://0.0.0.0:%d — data in %s", PORT, DATA_DIR)
    web.run_app(app, host="0.0.0.0", port=PORT, loop=loop, print=None)


if __name__ == "__main__":
    main()
