"""Data update coordinator for Park Visits.

Queries the Google Places API (New) "Nearby Search" endpoint, tiled across
several overlapping 50km-radius requests to cover the configured radius
(Google caps a single request's radius at 50km), then ranks the combined,
deduplicated results by rating and merges in our own stored reviews.

There is no automatic polling — `update_interval` is deliberately None.
The only things that ever trigger a Google API call are the initial fetch
when the integration is set up (or its options change) and the
"Refresh parks" button. Everything else (e.g. submitting a review) updates
entities from already-fetched data.
"""
from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass
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
    DEFAULT_MAX_PARKS,
    DEFAULT_RADIUS_KM,
    DOMAIN,
    MIN_RATING_COUNT,
    PLACES_API_BASE_URL,
    PLACES_API_FIELD_MASK,
    PLACES_API_INCLUDED_TYPES,
    PLACES_API_MAX_RESULTS_PER_TILE,
    PLACES_API_MAX_TILE_RADIUS_KM,
    PLACES_API_NOISE_TYPES,
)
from .storage import ManualParkStore, ParkListCache, ParkPlanStore, ParkReviewStore
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
    our_person_ratings: dict[str, float]
    our_playground_rating: float | None
    our_scenery_rating: float | None
    our_wildlife_rating: float | None
    our_facilities_rating: float | None
    our_parking_rating: float | None
    our_overall_rating: float | None
    our_note: str
    our_liked: str
    our_disliked: str
    our_photo_count: int
    our_visit_date: str | None
    # Defaulted so a park list cached by an earlier version still loads.
    manually_added: bool = False


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
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        reviews: ParkReviewStore,
        park_cache: ParkListCache,
        plan: ParkPlanStore,
        manual: ManualParkStore,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # manual refresh only — see module docstring
        )
        self.entry = entry
        self.reviews = reviews
        self.park_cache = park_cache
        self.plan = plan
        self.manual = manual
        # The fetched list, before manual parks are folded in. Kept so
        # adding or removing one can re-merge without re-querying Google.
        self._fetched: list[RankedPark] = []

    def settings_fingerprint(self) -> str:
        """Identifies the search parameters a cached park list was fetched with."""
        o = self.entry.options
        return "|".join(
            str(v)
            for v in (
                o.get(CONF_LATITUDE),
                o.get(CONF_LONGITUDE),
                o.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM),
                o.get(CONF_MAX_PARKS, DEFAULT_MAX_PARKS),
            )
        )

    async def async_load_cached(self) -> bool:
        """Populate from the on-disk park list instead of calling Google.

        Returns True when the cache was usable, so setup can skip the initial
        (paid) refresh entirely.
        """
        cached = await self.park_cache.async_load(self.settings_fingerprint())
        if not cached:
            return False
        try:
            parks = [RankedPark(**item) for item in cached]
        except TypeError:
            # Cache written by a version with different fields — ignore it and
            # let a real fetch rebuild it.
            return False

        # A cache written before the minimum-rating rule existed can still
        # hold thinly-rated parks. Re-apply the filter here so the rule takes
        # effect immediately rather than waiting for a (paid) refresh, and
        # renumber so the ranks stay contiguous.
        filtered = [p for p in parks if (p.rating_count or 0) >= MIN_RATING_COUNT]
        if len(filtered) != len(parks):
            for index, park in enumerate(filtered, start=1):
                park.rank = index
        parks = filtered
        if not parks:
            return False

        # Manual parks are merged on top of the cache rather than stored in
        # it: the cache belongs to the Google search and is keyed by the
        # search settings, so folding them in would mean adding a park could
        # invalidate the cache and trigger a paid refresh.
        self._fetched = parks
        self.async_set_updated_data(self._merge_manual(parks))
        await self.async_refresh_reviews()
        return True

    async def _async_update_data(self) -> list[RankedPark]:
        options = self.entry.options
        api_key = options.get(CONF_API_KEY)
        if not api_key:
            raise ConfigEntryAuthFailed("Missing Google Places API key")

        center_lat = options.get(CONF_LATITUDE)
        center_lon = options.get(CONF_LONGITUDE)
        if center_lat is None or center_lon is None:
            raise UpdateFailed(
                "No location is configured for Park Visits — open its options "
                "and choose a location"
            )
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
                    **self._review_fields(place_id),
                }
            )

        # Thinly-rated places are dropped before ranking, not after, so the
        # configured park count is filled with parks that actually qualify.
        candidates = [
            p for p in candidates if (p["rating_count"] or 0) >= MIN_RATING_COUNT
        ]

        # Rank by Google rating (best first). Rating count breaks ties so a
        # 5.0 from 6 reviews doesn't outrank a 4.9 from 2,000.
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

        # Persist so the next restart doesn't re-run this (paid) search.
        # Only what Google returned is cached — see _merge_manual.
        await self.park_cache.async_save(
            self.settings_fingerprint(), [asdict(p) for p in result]
        )
        self._fetched = result
        return self._merge_manual(result)

    def _review_fields(self, place_id: str) -> dict[str, Any]:
        """Our own review for a park, in the shape RankedPark expects."""
        review = self.reviews.get(place_id)
        return {
            "our_person_ratings": dict(review.person_ratings) if review else {},
            "our_playground_rating": review.playground_rating if review else None,
            "our_scenery_rating": review.scenery_rating if review else None,
            "our_wildlife_rating": review.wildlife_rating if review else None,
            "our_facilities_rating": review.facilities_rating if review else None,
            "our_parking_rating": review.parking_rating if review else None,
            "our_overall_rating": review.overall_rating if review else None,
            "our_note": review.note if review else "",
            "our_liked": review.liked if review else "",
            "our_disliked": review.disliked if review else "",
            "our_photo_count": len(review.photos) if review else 0,
            "our_visit_date": (review.visit_date or None) if review else None,
        }

    def _merge_manual(self, fetched: list[RankedPark]) -> list[RankedPark]:
        """Fold manually added parks into the fetched list and renumber.

        Deliberately applied *after* MIN_RATING_COUNT and the max_parks cap:
        a park added by hand was chosen on purpose, so neither the ranking
        rules nor the size limit may drop it. A park Google already returned
        is only flagged, not duplicated.
        """
        manual = self.manual.all_parks()
        options = self.entry.options
        center_lat = options.get(CONF_LATITUDE)
        center_lon = options.get(CONF_LONGITUDE)

        combined = list(fetched)
        already = {p.place_id for p in fetched}
        # Assigned rather than only set: these are the same objects held in
        # _fetched, so a park that was manual last time round has to be
        # cleared when it no longer is, and ranks have to be renumbered even
        # when nothing is manual — otherwise removing the last manual park
        # leaves everything renumbered around a gap.
        for park in combined:
            park.manually_added = park.place_id in manual

        for place_id, park in manual.items():
            if place_id in already:
                continue
            distance = (
                haversine_km(center_lat, center_lon, park["latitude"], park["longitude"])
                if center_lat is not None and center_lon is not None
                else 0.0
            )
            combined.append(
                RankedPark(
                    place_id=place_id,
                    unique_id=place_id,
                    rank=0,  # replaced by the renumber below
                    name=park["name"],
                    address=park.get("address", ""),
                    latitude=park["latitude"],
                    longitude=park["longitude"],
                    categories=list(park.get("categories") or []),
                    rating=park.get("rating"),
                    rating_count=park.get("rating_count", 0),
                    google_maps_uri=park.get("google_maps_uri"),
                    distance_km=distance,
                    manually_added=True,
                    **self._review_fields(place_id),
                )
            )

        # Same ordering rule as the fetched list, so a manually added park
        # sits where its rating says it should. One with no rating yet sorts
        # last until Place Details fills it in.
        combined.sort(
            key=lambda p: (p.rating is None, -(p.rating or 0), -(p.rating_count or 0))
        )
        for index, park in enumerate(combined, start=1):
            park.rank = index
        return combined

    async def async_add_manual_park(self, candidate: Any) -> None:
        """Track a park found by search, and show it immediately."""
        await self.manual.async_add(
            place_id=candidate.place_id,
            name=candidate.name,
            address=candidate.address,
            latitude=candidate.latitude,
            longitude=candidate.longitude,
            categories=candidate.categories,
            google_maps_uri=candidate.google_maps_uri,
            # Present when the park was resolved by id; 0/None from a text
            # search, and filled in later by async_note_google_rating.
            rating=getattr(candidate, "rating", None),
            rating_count=getattr(candidate, "rating_count", 0),
        )
        self.async_set_updated_data(self._merge_manual(self._fetched))

    async def async_remove_manual_park(self, place_id: str) -> bool:
        """Stop tracking a manually added park (its review is left alone)."""
        removed = await self.manual.async_remove(place_id)
        if removed:
            self.async_set_updated_data(self._merge_manual(self._fetched))
        return removed

    async def async_note_google_rating(
        self, place_id: str, rating: float | None, rating_count: int
    ) -> None:
        """Record a rating learned from Place Details for a manual park.

        The search that adds these parks doesn't pay for ratings, so this is
        where one arrives — free, off the back of the details call the card
        already makes when a park is opened.
        """
        if await self.manual.async_set_rating(place_id, rating, rating_count):
            self.async_set_updated_data(self._merge_manual(self._fetched))

    def park_name(self, place_id: str) -> str:
        """Current display name for a park, if it's still tracked."""
        if not self.data:
            return ""
        return next((p.name for p in self.data if p.place_id == place_id), "")

    def park_by_id(self, place_id: str) -> RankedPark | None:
        """The tracked park with this place_id, if it's still in the list."""
        if not self.data:
            return None
        return next((p for p in self.data if p.place_id == place_id), None)

    def next_park(self) -> dict[str, Any] | None:
        """The park we've planned to visit next, enriched with live details."""
        planned = self.plan.next_park
        if not planned:
            return None
        park = self.park_by_id(planned["place_id"])
        if park:
            planned.update(
                {
                    "park_name": park.name,
                    "rating": park.rating,
                    "rating_count": park.rating_count,
                    "distance_km": park.distance_km,
                    "categories": park.categories,
                    "address": park.address,
                    "still_tracked": True,
                }
            )
        else:
            planned["still_tracked"] = False
        return planned

    def last_visited(self) -> dict[str, Any] | None:
        """The most recently *visited* park, by the visit date chosen on the review.

        Read from the review store rather than the tracked list so a park that
        has since dropped out of the top N is still reported. Sorted by
        visit_date rather than when the review happened to be submitted, so
        back-dating a visit reorders this correctly.
        """
        latest_id = None
        latest = None
        for place_id, review in self.reviews.all_reviews().items():
            if not review.visit_date:
                continue
            if latest is None or review.visit_date > latest.visit_date:
                latest, latest_id = review, place_id
        if latest is None:
            return None

        park = self.park_by_id(latest_id)
        return {
            "place_id": latest_id,
            "park_name": (park.name if park else "") or latest.park_name or "Unknown park",
            "our_overall_rating": latest.overall_rating,
            "our_person_ratings": dict(latest.person_ratings),
            "our_liked": latest.liked,
            "our_disliked": latest.disliked,
            "our_note": latest.note,
            "our_photo_count": len(latest.photos),
            "visit_date": latest.visit_date,
            "rating": park.rating if park else None,
            "distance_km": park.distance_km if park else None,
            "still_tracked": park is not None,
        }

    async def async_set_next_park(self, place_id: str) -> None:
        await self.plan.async_set_next(place_id, self.park_name(place_id))
        self.async_update_listeners()

    async def async_clear_next_park(self) -> None:
        await self.plan.async_clear_next()
        self.async_update_listeners()

    async def async_submit_review(
        self,
        place_id: str,
        person_ratings: dict[str, float],
        visit_date: str,
        playground_rating: float | None = None,
        scenery_rating: float | None = None,
        wildlife_rating: float | None = None,
        facilities_rating: float | None = None,
        parking_rating: float | None = None,
        note: str = "",
        liked: str = "",
        disliked: str = "",
    ) -> None:
        """Record a review locally and refresh entities without hitting the API."""
        await self.reviews.async_set_review(
            place_id,
            person_ratings,
            visit_date,
            playground_rating=playground_rating,
            scenery_rating=scenery_rating,
            wildlife_rating=wildlife_rating,
            facilities_rating=facilities_rating,
            parking_rating=parking_rating,
            liked=liked,
            disliked=disliked,
            note=note,
            park_name=self.park_name(place_id),
        )
        # Reviewing the park that was queued up means we've been — so it stops
        # being "next". Leaving it there would show a park as both the last
        # visited and the next to visit.
        planned = self.plan.next_park
        if planned and planned.get("place_id") == place_id:
            await self.plan.async_clear_next()
        await self.async_refresh_reviews()

    async def async_delete_review(self, place_id: str) -> list[str]:
        """Drop a review and report its photo filenames so they can be deleted."""
        filenames = await self.reviews.async_delete_review(place_id)
        await self.async_refresh_reviews()
        return filenames

    async def async_remove_photo(self, place_id: str, filename: str) -> None:
        """Detach one photo from a review and refresh entities."""
        await self.reviews.async_remove_photo(place_id, filename)
        await self.async_refresh_reviews()

    async def async_refresh_reviews(self) -> None:
        """Re-apply stored reviews onto the current park list, no API call.

        Used after a review or photo upload: the Google-sourced data is
        unchanged, so re-fetching it would spend quota for nothing.
        """
        if not self.data:
            return
        for park in self.data:
            for field_name, value in self._review_fields(park.place_id).items():
                setattr(park, field_name, value)
        self.async_set_updated_data(self.data)
