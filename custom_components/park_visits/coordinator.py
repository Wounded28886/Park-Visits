"""Data update coordinator for Park Visits.

The underlying dataset is a bundled, curated JSON file (no external API
calls), so "updates" just recompute the filtered/ranked list from the
current config entry options. This still runs through a DataUpdateCoordinator
so entities get standard availability handling and a periodic refresh.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_MAX_PARKS,
    CONF_RADIUS_KM,
    DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE,
    DEFAULT_MAX_PARKS,
    DEFAULT_RADIUS_KM,
    DOMAIN,
)
from .util import haversine_km, load_parks

_LOGGER = logging.getLogger(__name__)
UPDATE_INTERVAL = timedelta(hours=6)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    return _SLUG_RE.sub("_", name.lower()).strip("_")


@dataclass
class RankedPark:
    """A single park with its computed distance, ready for display."""

    unique_id: str
    rank: int
    name: str
    locality: str
    latitude: float
    longitude: float
    category: str
    description: str
    distance_km: float


class ParkVisitsCoordinator(DataUpdateCoordinator[list[RankedPark]]):
    """Filters and ranks the bundled parks dataset around a configurable centre point."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=UPDATE_INTERVAL)
        self.entry = entry
        self._raw_parks = load_parks()

    async def _async_update_data(self) -> list[RankedPark]:
        return self._compute()

    def _compute(self) -> list[RankedPark]:
        options = self.entry.options
        center_lat = options.get(CONF_LATITUDE, DEFAULT_LATITUDE)
        center_lon = options.get(CONF_LONGITUDE, DEFAULT_LONGITUDE)
        radius_km = options.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM)
        max_parks = options.get(CONF_MAX_PARKS, DEFAULT_MAX_PARKS)

        in_range: list[tuple[dict, float]] = []
        for park in self._raw_parks:
            distance = haversine_km(center_lat, center_lon, park["lat"], park["lon"])
            if distance <= radius_km:
                in_range.append((park, distance))

        # Curated popularity rank ascending = most popular/notable first.
        in_range.sort(key=lambda item: item[0]["rank"])
        top = in_range[:max_parks]

        seen_slugs: dict[str, int] = {}
        ranked: list[RankedPark] = []
        for display_rank, (park, distance) in enumerate(top, start=1):
            slug = _slugify(park["name"])
            count = seen_slugs.get(slug, 0)
            seen_slugs[slug] = count + 1
            unique_id = slug if count == 0 else f"{slug}_{count}"
            ranked.append(
                RankedPark(
                    unique_id=unique_id,
                    rank=display_rank,
                    name=park["name"],
                    locality=park.get("locality", ""),
                    latitude=park["lat"],
                    longitude=park["lon"],
                    category=park.get("category", "park"),
                    description=park.get("description", ""),
                    distance_km=round(distance, 1),
                )
            )
        return ranked
