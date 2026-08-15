"""Thin Immich API client.

Only three things are needed: list the tags you can pick from, find the
assets carrying a given tag, and fetch a thumbnail. Everything runs
server-side — an Immich API key is as sensitive as the Google one, so it
never reaches the browser (see views.py for how images are relayed).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import IMMICH_MAX_ASSETS, IMMICH_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class ImmichError(Exception):
    """Immich could not be reached, or rejected the request."""


@dataclass(frozen=True)
class ImmichTag:
    id: str
    name: str


@dataclass(frozen=True)
class ImmichAsset:
    id: str
    file_name: str
    taken_at: str | None


def _redirect_error(location: str) -> ImmichError:
    """A 3xx from the API means something is standing in front of Immich.

    Typically a reverse proxy with its own auth (Cloudflare Access, Authelia,
    a login portal): it bounces the request to a sign-in page, and the
    x-api-key header means nothing to it. Following the redirect would just
    yield HTML and a baffling parse error, so say what actually happened.
    """
    host = location.split("/")[2] if "//" in location else location
    return ImmichError(
        f"The Immich URL redirected to {host} — something in front of Immich "
        "(a login portal or access proxy) is intercepting API calls. Use an "
        "address that reaches Immich directly, such as its LAN address."
    )


def _base(url: str) -> str:
    """Normalise the configured server URL to a bare origin."""
    url = (url or "").strip().rstrip("/")
    # Tolerate someone pasting the API root or a UI path.
    for suffix in ("/api",):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url


class ImmichClient:
    """Talks to one Immich server."""

    def __init__(self, hass: HomeAssistant, url: str, api_key: str) -> None:
        self._hass = hass
        self._base = _base(url)
        self._api_key = (api_key or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self._base and self._api_key)

    @property
    def base_url(self) -> str:
        return self._base

    async def _request(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None
    ) -> Any:
        if not self.configured:
            raise ImmichError("Immich is not configured")
        session = async_get_clientsession(self._hass)
        url = f"{self._base}/api{path}"
        try:
            async with session.request(
                method,
                url,
                json=json_body,
                headers={"x-api-key": self._api_key, "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=IMMICH_TIMEOUT),
                allow_redirects=False,
            ) as response:
                if 300 <= response.status < 400:
                    raise _redirect_error(response.headers.get("Location", ""))
                if response.status in (401, 403):
                    raise ImmichError("Immich rejected the API key")
                if response.status != 200:
                    text = await response.text()
                    raise ImmichError(f"Immich returned {response.status}: {text[:160]}")
                return await response.json()
        except aiohttp.ClientError as err:
            raise ImmichError(f"Could not reach Immich: {err}") from err

    async def async_list_tags(self) -> list[ImmichTag]:
        """Every tag defined on the server, alphabetically."""
        raw = await self._request("GET", "/tags")
        tags = [
            ImmichTag(id=item["id"], name=item.get("name") or item.get("value") or "")
            for item in raw or []
            if item.get("id")
        ]
        return sorted(tags, key=lambda t: t.name.lower())

    async def async_assets_for_tag(self, tag_id: str) -> list[ImmichAsset]:
        """Photos carrying a tag, newest first.

        Videos are filtered out: the gallery renders <img>, and a video
        thumbnail that can't be played is more confusing than useful.
        """
        raw = await self._request(
            "POST",
            "/search/metadata",
            json_body={
                "tagIds": [tag_id],
                "size": IMMICH_MAX_ASSETS,
                "order": "desc",
                "type": "IMAGE",
            },
        )
        items = ((raw or {}).get("assets") or {}).get("items") or []
        return [
            ImmichAsset(
                id=item["id"],
                file_name=item.get("originalFileName", ""),
                taken_at=item.get("localDateTime") or item.get("fileCreatedAt"),
            )
            for item in items
            if item.get("id")
        ]

    async def async_thumbnail(self, asset_id: str) -> tuple[bytes, str]:
        """Raw thumbnail bytes plus content type, for relaying to the browser."""
        if not self.configured:
            raise ImmichError("Immich is not configured")
        session = async_get_clientsession(self._hass)
        url = f"{self._base}/api/assets/{asset_id}/thumbnail"
        try:
            async with session.get(
                url,
                params={"size": "preview"},
                headers={"x-api-key": self._api_key},
                timeout=aiohttp.ClientTimeout(total=IMMICH_TIMEOUT),
                allow_redirects=False,
            ) as response:
                if 300 <= response.status < 400:
                    raise _redirect_error(response.headers.get("Location", ""))
                if response.status != 200:
                    raise ImmichError(f"Thumbnail returned {response.status}")
                return (
                    await response.read(),
                    response.headers.get("Content-Type", "image/jpeg").split(";")[0].strip(),
                )
        except aiohttp.ClientError as err:
            raise ImmichError(f"Could not reach Immich: {err}") from err
