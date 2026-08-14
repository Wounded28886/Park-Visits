"""HTTP endpoints backing the Park Visits dashboard card.

Three jobs, all of which have to happen server-side:

* **Place Details** — Google's reviews/photos sit on a pricier SKU than the
  bulk Nearby Search, so they're fetched per-park on demand and cached.
* **Photo proxying** — a Google photo URL needs the API key. Putting that in
  an ``<img src>`` would hand the key to every browser that loads the page,
  so the bytes are fetched here and relayed.
* **Our own photos** — uploaded and served from disk.

The two image endpoints run with ``requires_auth = False`` because an
``<img>`` tag cannot send an Authorization header. They are instead reached
through Home Assistant's signed-path mechanism (``auth/sign_path``), which
mints a short-lived HMAC-signed URL: the card requests one, drops it in the
``src``, and HA rejects any unsigned request before it reaches the handler.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    ALLOWED_PHOTO_TYPES,
    CONF_API_KEY,
    DETAILS_CACHE_HOURS,
    DOMAIN,
    GOOGLE_PHOTO_MAX_WIDTH,
    MAX_GOOGLE_PHOTOS,
    MAX_UPLOAD_BYTES,
    PHOTO_DIR_NAME,
    PLACES_API_DETAILS_FIELD_MASK,
    PLACES_API_DETAILS_URL,
    PLACES_API_PHOTO_URL,
)

_LOGGER = logging.getLogger(__name__)

# place_id values are opaque Google strings; constrain them anyway since they
# are interpolated into URLs and used as directory names.
_PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,255}$")
_FILENAME_RE = re.compile(r"^[a-f0-9]{32}\.(jpg|png|webp|gif)$")


def photo_dir(hass: HomeAssistant, place_id: str) -> str:
    """Absolute path to a park's own-photo directory."""
    return hass.config.path(PHOTO_DIR_NAME, place_id)


def is_safe_photo_target(place_id: str, filename: str) -> bool:
    """Whether these came from us and can't escape the photo directory."""
    return bool(_PLACE_ID_RE.match(place_id) and _FILENAME_RE.match(filename))


async def async_delete_photo_files(
    hass: HomeAssistant, place_id: str, filenames: list[str]
) -> int:
    """Delete photo files from disk, returning how many were removed.

    Missing files are not an error — the point is that they end up gone.
    """
    if not _PLACE_ID_RE.match(place_id):
        return 0
    directory = photo_dir(hass, place_id)

    def _delete() -> int:
        removed = 0
        for filename in filenames:
            if not _FILENAME_RE.match(filename):
                continue
            path = os.path.join(directory, filename)
            if not os.path.realpath(path).startswith(os.path.realpath(directory) + os.sep):
                continue
            try:
                os.remove(path)
                removed += 1
            except FileNotFoundError:
                pass
            except OSError as err:
                _LOGGER.warning("Could not delete photo %s: %s", path, err)
        # Tidy up the park's folder once it holds nothing.
        try:
            if os.path.isdir(directory) and not os.listdir(directory):
                os.rmdir(directory)
        except OSError:
            pass
        return removed

    return await hass.async_add_executor_job(_delete)


def _entry_data(hass: HomeAssistant) -> dict[str, Any] | None:
    """Runtime data for the (single) config entry, if the integration is loaded."""
    for value in hass.data.get(DOMAIN, {}).values():
        if isinstance(value, dict) and "coordinator" in value:
            return value
    return None


def _api_key(hass: HomeAssistant) -> str | None:
    data = _entry_data(hass)
    return data["coordinator"].entry.options.get(CONF_API_KEY) if data else None


@dataclass
class _CachedDetails:
    """One park's Place Details, plus the raw photo names the proxy needs."""

    fetched_at: datetime
    payload: dict[str, Any]
    photo_names: list[str] = field(default_factory=list)


class DetailsCache:
    """Shared between the details endpoint and the photo proxy.

    The proxy serves photos by index so the card never sees Google's photo
    resource names; this is where that index is resolved.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _CachedDetails] = {}

    def get_fresh(self, place_id: str) -> _CachedDetails | None:
        entry = self._entries.get(place_id)
        if not entry:
            return None
        if datetime.now(timezone.utc) - entry.fetched_at >= timedelta(hours=DETAILS_CACHE_HOURS):
            return None
        return entry

    def put(self, place_id: str, payload: dict[str, Any], photo_names: list[str]) -> None:
        self._entries[place_id] = _CachedDetails(
            fetched_at=datetime.now(timezone.utc), payload=payload, photo_names=photo_names
        )

    def photo_names(self, place_id: str) -> list[str]:
        entry = self._entries.get(place_id)
        return entry.photo_names if entry else []


def _shape_details(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Reduce Google's response to what the card renders, plus photo names."""
    reviews = []
    for review in (raw.get("reviews") or [])[:5]:
        author = review.get("authorAttribution") or {}
        text_block = review.get("originalText") or review.get("text") or {}
        reviews.append(
            {
                "author": author.get("displayName", "Anonymous"),
                "author_photo": author.get("photoUri"),
                "rating": review.get("rating"),
                "text": text_block.get("text", ""),
                "relative_time": review.get("relativePublishTimeDescription", ""),
            }
        )

    photo_names = [
        p["name"] for p in (raw.get("photos") or [])[:MAX_GOOGLE_PHOTOS] if p.get("name")
    ]

    payload = {
        "place_id": raw.get("id"),
        "name": (raw.get("displayName") or {}).get("text", ""),
        "address": raw.get("formattedAddress", ""),
        "rating": raw.get("rating"),
        "rating_count": raw.get("userRatingCount", 0),
        "google_maps_uri": raw.get("googleMapsUri"),
        "website": raw.get("websiteUri"),
        "phone": raw.get("nationalPhoneNumber"),
        "summary": (raw.get("editorialSummary") or {}).get("text", ""),
        "opening_hours": (raw.get("currentOpeningHours") or {}).get("weekdayDescriptions") or [],
        "reviews": reviews,
        "photo_count": len(photo_names),
    }
    return payload, photo_names


class ParkDetailsView(HomeAssistantView):
    """Fetch (and cache) Google Place Details for one park."""

    url = "/api/park_visits/details/{place_id}"
    name = "api:park_visits:details"
    requires_auth = True

    def __init__(self, hass: HomeAssistant, cache: DetailsCache) -> None:
        self.hass = hass
        self._cache = cache

    def _our_photos(self, place_id: str) -> list[str]:
        """Filenames of our own photos.

        Always read live rather than cached with the Google payload: a photo
        uploaded a minute ago must show up immediately, not in 24 hours.
        """
        data = _entry_data(self.hass)
        if not data:
            return []
        review = data["reviews"].get(place_id)
        return list(review.photos) if review else []

    async def get(self, request: web.Request, place_id: str) -> web.Response:
        if not _PLACE_ID_RE.match(place_id):
            return self.json_message("Invalid place_id", 400)

        cached = self._cache.get_fresh(place_id)
        if cached:
            return self.json(
                {**cached.payload, "cached": True, "our_photos": self._our_photos(place_id)}
            )

        api_key = _api_key(self.hass)
        if not api_key:
            return self.json_message("Park Visits is not configured", 503)

        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                PLACES_API_DETAILS_URL.format(place_id=place_id),
                headers={
                    "X-Goog-Api-Key": api_key,
                    "X-Goog-FieldMask": PLACES_API_DETAILS_FIELD_MASK,
                },
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    _LOGGER.warning(
                        "Place Details failed for %s: %s %s",
                        place_id,
                        response.status,
                        text[:200],
                    )
                    return self.json_message(f"Google returned {response.status}", 502)
                raw = await response.json()
        except aiohttp.ClientError as err:
            _LOGGER.warning("Place Details request error for %s: %s", place_id, err)
            return self.json_message("Could not reach Google", 502)

        payload, photo_names = _shape_details(raw)
        self._cache.put(place_id, payload, photo_names)
        return self.json(
            {**payload, "cached": False, "our_photos": self._our_photos(place_id)}
        )


class GooglePhotoView(HomeAssistantView):
    """Relay a Google Places photo so the API key stays on the server."""

    url = "/api/park_visits/google_photo/{place_id}/{index}"
    name = "api:park_visits:google_photo"
    requires_auth = False  # signed path — see module docstring

    def __init__(self, hass: HomeAssistant, cache: DetailsCache) -> None:
        self.hass = hass
        self._cache = cache

    async def get(
        self, request: web.Request, place_id: str, index: str
    ) -> web.StreamResponse:
        if not _PLACE_ID_RE.match(place_id) or not index.isdigit():
            return web.Response(status=400, text="Invalid request")

        names = self._cache.photo_names(place_id)
        idx = int(index)
        if idx >= len(names):
            # Details expired or were never fetched — the card should reopen
            # the park, which repopulates the cache.
            return web.Response(status=404, text="Unknown photo")

        api_key = _api_key(self.hass)
        if not api_key:
            return web.Response(status=503, text="Not configured")

        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                PLACES_API_PHOTO_URL.format(photo_name=names[idx]),
                params={"maxWidthPx": str(GOOGLE_PHOTO_MAX_WIDTH), "key": api_key},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                if response.status != 200:
                    return web.Response(status=502, text="Photo unavailable")
                body = await response.read()
                content_type = response.headers.get("Content-Type", "image/jpeg")
        except aiohttp.ClientError:
            return web.Response(status=502, text="Photo unavailable")

        return web.Response(
            body=body,
            content_type=content_type.split(";")[0].strip(),
            headers={"Cache-Control": "private, max-age=86400"},
        )


class OurPhotoView(HomeAssistantView):
    """Serve a photo we uploaded ourselves."""

    url = "/api/park_visits/photo/{place_id}/{filename}"
    name = "api:park_visits:photo"
    requires_auth = False  # signed path

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(
        self, request: web.Request, place_id: str, filename: str
    ) -> web.StreamResponse:
        if not _PLACE_ID_RE.match(place_id) or not _FILENAME_RE.match(filename):
            return web.Response(status=400, text="Invalid request")

        directory = photo_dir(self.hass, place_id)
        path = os.path.join(directory, filename)
        # The regexes already exclude traversal sequences; confirm the resolved
        # path really sits inside the park's directory before opening it.
        if not os.path.realpath(path).startswith(os.path.realpath(directory) + os.sep):
            return web.Response(status=400, text="Invalid request")
        if not await self.hass.async_add_executor_job(os.path.isfile, path):
            return web.Response(status=404, text="Not found")
        return web.FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


class UploadPhotoView(HomeAssistantView):
    """Accept one of our own photos for a park."""

    url = "/api/park_visits/upload/{place_id}"
    name = "api:park_visits:upload"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def post(self, request: web.Request, place_id: str) -> web.Response:
        if not _PLACE_ID_RE.match(place_id):
            return self.json_message("Invalid place_id", 400)

        data = _entry_data(self.hass)
        if not data:
            return self.json_message("Park Visits is not configured", 503)

        try:
            reader = await request.multipart()
            part = await reader.next()
            while part is not None and part.name != "photo":
                part = await reader.next()
        except Exception:  # noqa: BLE001 — malformed multipart from a client
            return self.json_message("Malformed upload", 400)
        if part is None:
            return self.json_message("No photo field in upload", 400)

        content_type = (part.headers.get("Content-Type") or "").split(";")[0].strip()
        extension = ALLOWED_PHOTO_TYPES.get(content_type)
        if not extension:
            return self.json_message(f"Unsupported image type '{content_type}'", 400)

        # Read with a hard cap rather than trusting Content-Length, which the
        # client controls.
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = await part.read_chunk()
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                return self.json_message("Photo too large", 413)
            chunks.append(chunk)
        if not size:
            return self.json_message("Empty upload", 400)

        filename = f"{uuid.uuid4().hex}{extension}"
        directory = photo_dir(self.hass, place_id)

        def _write() -> None:
            os.makedirs(directory, exist_ok=True)
            with open(os.path.join(directory, filename), "wb") as handle:
                handle.write(b"".join(chunks))

        await self.hass.async_add_executor_job(_write)

        coordinator = data["coordinator"]
        park_name = ""
        if coordinator.data:
            park_name = next(
                (p.name for p in coordinator.data if p.place_id == place_id), ""
            )
        await data["reviews"].async_add_photo(place_id, filename, park_name=park_name)
        await coordinator.async_refresh_reviews()

        return self.json({"filename": filename})


class GalleryView(HomeAssistantView):
    """Every review that has photos, for the gallery card."""

    url = "/api/park_visits/gallery"
    name = "api:park_visits:gallery"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        data = _entry_data(self.hass)
        if not data:
            return self.json_message("Park Visits is not configured", 503)

        # Prefer the live park name; fall back to the one saved with the
        # review, which is all we have once a park leaves the tracked list.
        live_names = {}
        coordinator = data["coordinator"]
        if coordinator.data:
            live_names = {p.place_id: p.name for p in coordinator.data}

        items = []
        for place_id, review in data["reviews"].all_reviews().items():
            if not review.photos:
                continue
            items.append(
                {
                    "place_id": place_id,
                    "name": live_names.get(place_id) or review.park_name or "Unknown park",
                    "overall_rating": review.overall_rating,
                    "kids_rating": review.kids_rating,
                    "mums_rating": review.mums_rating,
                    "dads_rating": review.dads_rating,
                    "liked": review.liked,
                    "disliked": review.disliked,
                    "note": review.note,
                    "visit_date": review.visit_date or None,
                    "photos": list(review.photos),
                    "still_tracked": place_id in live_names,
                }
            )
        items.sort(key=lambda i: i["visit_date"] or "", reverse=True)
        return self.json({"parks": items})


def async_register_views(hass: HomeAssistant) -> None:
    """Register all Park Visits HTTP endpoints (once per HA run)."""
    cache = DetailsCache()
    hass.http.register_view(ParkDetailsView(hass, cache))
    hass.http.register_view(GooglePhotoView(hass, cache))
    hass.http.register_view(OurPhotoView(hass))
    hass.http.register_view(UploadPhotoView(hass))
    hass.http.register_view(GalleryView(hass))
