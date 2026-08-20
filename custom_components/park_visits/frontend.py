"""Serves the bundled Lovelace cards and gets them loaded on every dashboard.

The cards live in custom_components/park_visits/www/ (inside the integration
itself) rather than a top-level www/ folder, so HACS updates them along with
the integration — no manual copy to config/www.

Getting a browser to actually *run* them is the fiddly part, and there are
two mechanisms:

* A **Lovelace resource**, which is how every HACS card is loaded. Preferred.
* ``add_extra_js_url()``, which injects a dynamic ``import()`` into the page.
  Needs no storage collection, so it's the fallback for YAML-mode setups.

Only one is used, deliberately. Registering both would download and parse the
same card twice on every page load, and — because both URLs would name the
same file — the browser can deduplicate them into a single module that then
fails to evaluate, leaving Home Assistant reporting "Custom element doesn't
exist" for a card that is perfectly fine. That failure was observed on a
Samsung Family Hub display, which Home Assistant serves its legacy ES5
frontend to; the resource path fixed it where the extra-module URL never did.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

URL_BASE = "/park_visits_frontend"
CARD_FILES = ("park-visits-table-card.js", "park-visits-gallery-card.js")
WWW_DIR = Path(__file__).parent / "www"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve WWW_DIR at URL_BASE and make sure the cards get loaded."""
    try:
        # Home Assistant 2024.7+.
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(URL_BASE, str(WWW_DIR), True)]
        )
    except ImportError:
        # Older Home Assistant only has the synchronous helper.
        hass.http.register_static_path(URL_BASE, str(WWW_DIR), True)

    # Static paths are served with a month-long Cache-Control, so without a
    # changing URL a browser keeps an updated card for weeks — the update
    # lands on disk and simply isn't used. Tying the query string to the
    # manifest version makes every release a new URL, picked up on the next
    # page load instead of needing a manual cache clear.
    version = await _async_card_version(hass)

    if await _async_sync_resources(hass, version):
        return

    _LOGGER.debug("Lovelace resources unavailable; falling back to extra_js_url")
    for filename in CARD_FILES:
        add_extra_js_url(hass, f"{URL_BASE}/{filename}?v={version}")


def _resource_collection(hass: HomeAssistant) -> Any | None:
    """The editable Lovelace resource collection, if this install has one.

    Only storage mode has one that can be written to; a YAML-mode install
    lists its resources in configuration.yaml and must be left alone.
    """
    data = hass.data.get("lovelace")
    if data is None:
        return None

    # Recent Home Assistant exposes a LovelaceData dataclass here; older
    # versions used a plain dict.
    if isinstance(data, dict):
        resources = data.get("resources")
        mode = data.get("mode")
    else:
        resources = getattr(data, "resources", None)
        mode = getattr(data, "mode", None)

    if mode != "storage" or resources is None:
        return None
    # The YAML-backed collection has no create/update methods.
    if not hasattr(resources, "async_create_item"):
        return None
    return resources


async def _async_sync_resources(hass: HomeAssistant, version: str) -> bool:
    """Register/refresh a Lovelace resource per card. True if that worked.

    Rewriting the URL on every version change is the point: the resource is
    what the browser fetches, so a stale URL means a device happily runs last
    month's card forever. Only resources under URL_BASE are touched.
    """
    resources = _resource_collection(hass)
    if resources is None:
        return False

    try:
        # Loads the collection on first access.
        if hasattr(resources, "async_get_info"):
            await resources.async_get_info()
        elif not getattr(resources, "loaded", True):
            await resources.async_load()

        existing = list(resources.async_items())
        for filename in CARD_FILES:
            path = f"{URL_BASE}/{filename}"
            wanted = f"{path}?res={version}"
            ours = [
                item
                for item in existing
                if str(item.get("url", "")).split("?")[0] == path
            ]

            if not ours:
                await resources.async_create_item({"res_type": "module", "url": wanted})
                _LOGGER.debug("Registered Lovelace resource %s", wanted)
                continue

            keep = ours[0]
            if keep.get("url") != wanted:
                await resources.async_update_item(keep["id"], {"url": wanted})
                _LOGGER.debug("Updated Lovelace resource to %s", wanted)
            # A duplicate would load the card a second time, and the second
            # registration of the element name throws.
            for duplicate in ours[1:]:
                await resources.async_delete_item(duplicate["id"])
                _LOGGER.debug("Removed duplicate resource %s", duplicate.get("url"))
    except Exception as err:  # noqa: BLE001 - fall back rather than fail setup
        _LOGGER.warning(
            "Could not register the cards as Lovelace resources (%s); "
            "falling back to injecting them on every page instead",
            err,
        )
        return False

    return True


async def _async_card_version(hass: HomeAssistant) -> str:
    """The integration's manifest version, used to bust the browser cache.

    Falls back to the file modification time so a development install (or a
    manifest without a version) still refreshes when the card changes.
    """
    try:
        integration = await async_get_integration(hass, DOMAIN)
        if integration.version:
            return str(integration.version)
    except Exception as err:  # noqa: BLE001 - never block setup over a cache hint
        _LOGGER.debug("Could not read integration version: %s", err)

    def _newest_mtime() -> int:
        return max(
            (int((WWW_DIR / name).stat().st_mtime) for name in CARD_FILES),
            default=0,
        )

    try:
        return str(await hass.async_add_executor_job(_newest_mtime))
    except OSError:
        return "0"
