"""Data update coordinator for Park Visits.

Queries the Google Places API (New) "Nearby Search" endpoint, tiled across
several overlapping 50km-radius requests to cover the configured radius
(Google caps a single request's radius at 50km), then ranks the combined,
deduplicated results by rating and merges in our own stored reviews.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_API_KEY,
    CONF_MAX_PARKS,
    CONF_RADIUS_KM,
    DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE,
    DEFAULT_MAX_PARKS,
    DEFAULT_RADIUS_KM,
    DOMAIN,
    PLACES_API_BASE_URL,
    PLACES_API_FIELD_MASK,
    PLACES_API_INCLUDED_TYPES,
    PLACES_API_MAX_RESULTS_PER_TILE,
    PLACES_API_MAX_TILE_RADIUS_KM,
    PLACES_API_NOISE_TYPES,
    UPDATE_INTERVAL_HOURS,
)
from .storage import ParkReviewStore
from .util import destination_point, haversine_km

_LOGGER = logging.getLogger(__name__)


@dataclass
class RankedPark:
    """A single park with computed distance and our own review, ready for display."""

    place_id: str
    unique_id: str
    rank: int
    name: str
    address: str
    latitude: float
    longitude: float
    categories: list[str]
    rating: float | None
    rating_count: int
    google_maps_uri: str | None
    distance_km: float
    our_rating: float | None
    our_note: str
    our_reviewed_at: str | None


def _tile_centers(
    center_lat: float, center_lon: float, radius_km: float
) -> list[tuple[float, float]]:
    """Search-centre points whose 50km-radius circles cover the full requested radius.

    One request at the centre point covers the inner 50km. If the configured
    radius is bigger, additional rings of search centres are added further
    out, with enough points per ring that adjacent 50km circles overlap.
    This favours simplicity and generous overlap over perfectly efficient
    tiling — a few extra (cheap) requests is a fair trade for full coverage.
    """
    tile_radius = PLACES_API_MAX_TILE_RADIUS_KM
    centers = [(center_lat, center_lon)]
    if radius_km <= tile_radius:
        return centers

    ring_distance = float(tile_radius)
    ring_step = tile_radius * 1.5
    while ring_distance - tile_radius < radius_km:
        circumference_km = 2 * math.pi * ring_distance
        n_points = max(6, math.ceil(circumference_km / (1.5 * tile_radius)))
        for i in range(n_points):
            bearing = (360 / n_points) * i
            centers.append(destination_point(center_lat, center_lon, ring_distance, bearing))
        ring_distance += ring_step
    return centers


class ParkVisitsCoordinator(DataUpdateCoordinator[list[RankedPark]]):
    """Fetches nearby parks from Google Places and ranks them by rating."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, reviews: ParkReviewStore
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=UPDATE_INTERVAL_HOURS),
        )
        self.entry = entry
        self.reviews = reviews

    async def _async_update_data(self) -> list[RankedPark]:
        options = self.entry.options
        api_key = options.get(CONF_API_KEY)
        if not api_key:
            raise ConfigEntryAuthFailed("Missing Google Places API key")

        center_lat = options.get(CONF_LATITUDE, DEFAULT_LATITUDE)
        center_lon = options.get(CONF_LONGITUDE, DEFAULT_LONGITUDE)
        radius_km = options.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM)
        max_parks = options.get(CONF_MAX_PARKS, DEFAULT_MAX_PARKS)

        session = async_get_clientsession(self.hass)
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": PLACES_API_FIELD_MASK,
        }

        places_by_id: dict[str, dict[str, Any]] = {}
        for tile_lat, tile_lon in _tile_centers(center_lat, center_lon, radius_km):
            body = {
                "includedTypes": PLACES_API_INCLUDED_TYPES,
                "maxResultCount": PLACES_API_MAX_RESULTS_PER_TILE,
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": tile_lat, "longitude": tile_lon},
                        "radius": PLACES_API_MAX_TILE_RADIUS_KM * 1000,
                    }
                },
            }
            try:
                async with session.post(
                    PLACES_API_BASE_URL,
                    json=body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as response:
                    if response.status in (401, 403):
                        raise ConfigEntryAuthFailed(
                            f"Google Places API rejected the request "
                            f"({response.status}) — check the API key"
                        )
                    if response.status != 200:
                        text = await response.text()
                        raise UpdateFailed(
                            f"Google Places API error {response.status}: {text[:200]}"
                        )
                    payload = await response.json()
            except aiohttp.ClientError as err:
                raise UpdateFailed(f"Error talking to Google Places API: {err}") from err

            for place in payload.get("places", []):
                place_id = place.get("id")
                if place_id and place_id not in places_by_id:
                    places_by_id[place_id] = place

        reviews = self.reviews.all_reviews()
        candidates: list[dict[str, Any]] = []
        for place_id, place in places_by_id.items():
            location = place.get("location", {})
            lat = location.get("latitude")
            lon = location.get("longitude")
            if lat is None or lon is None:
                continue
            categories = [
                t.replace("_", " ").title()
                for t in place.get("types", [])
                if t not in PLACES_API_NOISE_TYPES
            ]
            review = reviews.get(place_id)
            candidates.append(
                {
                    "place_id": place_id,
                    "name": place.get("displayName", {}).get("text", "Unnamed park"),
                    "address": place.get("formattedAddress", ""),
                    "latitude": lat,
                    "longitude": lon,
                    "categories": categories,
                    "rating": place.get("rating"),
                    "rating_count": place.get("userRatingCount", 0),
                    "google_maps_uri": place.get("googleMapsUri"),
                    "distance_km": haversine_km(center_lat, center_lon, lat, lon),
                    "our_rating": review.rating if review else None,
                    "our_note": review.note if review else "",
                    "our_reviewed_at": review.reviewed_at if review else None,
                }
            )

        # Rank by Google rating (best first); unrated places sort last. Rating
        # count breaks ties so a 5.0 from 2 reviews doesn't outrank a 4.9 from
        # 2,000.
        candidates.sort(
            key=lambda p: (p["rating"] is None, -(p["rating"] or 0), -p["rating_count"])
        )
        top = candidates[:max_parks]

        seen_ids: dict[str, int] = {}
        result: list[RankedPark] = []
        for display_rank, park in enumerate(top, start=1):
            count = seen_ids.get(park["place_id"], 0)
            seen_ids[park["place_id"]] = count + 1
            unique_id = park["place_id"] if count == 0 else f"{park['place_id']}_{count}"
            result.append(RankedPark(rank=display_rank, unique_id=unique_id, **park))
        return result

    async def async_submit_review(self, place_id: str, rating: float, note: str) -> None:
        """Record a review locally and refresh entities without hitting the API."""
        review = await self.reviews.async_set_review(place_id, rating, note)
        if self.data:
            for park in self.data:
                if park.place_id == place_id:
                    park.our_rating = review.rating
                    park.our_note = review.note
                    park.our_reviewed_at = review.reviewed_at
                    break
        self.async_set_updated_data(self.data)
