"""Serves the bundled Lovelace cards and registers them on every dashboard.

The cards live in custom_components/park_visits/www/ (inside the
integration itself) rather than a top-level www/ folder, so HACS updates
them along with the integration on every update — no manual copy to
config/www, and add_extra_js_url() injects the <script> tag on every
frontend page load, so there's no manual "Add Resource" step either.
"""
from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.core import HomeAssistant

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

    for filename in CARD_FILES:
        add_extra_js_url(hass, f"{URL_BASE}/{filename}")
