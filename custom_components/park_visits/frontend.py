"""Serves the bundled Lovelace cards and registers them on every dashboard.

The cards live in custom_components/park_visits/www/ (inside the
integration itself) rather than a top-level www/ folder, so HACS updates
them along with the integration on every update — no manual copy to
config/www, and add_extra_js_url() injects the <script> tag on every
frontend page load, so there's no manual "Add Resource" step either.
"""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

URL_BASE = "/park_visits_frontend"
CARD_FILES = ("park-visits-table-card.js", "park-visits-gallery-card.js")
WWW_DIR = Path(__file__).parent / "www"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve WWW_DIR at URL_BASE and add each card as an extra module URL."""
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
    # manifest version makes every release a new URL, so an update is picked
    # up on the next page load instead of needing a manual cache clear.
    version = await _async_card_version(hass)
    for filename in CARD_FILES:
        add_extra_js_url(hass, f"{URL_BASE}/{filename}?v={version}")


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
