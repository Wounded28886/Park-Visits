"""Persistent storage for our own park reviews.

Keyed by Google place_id so a review survives dataset refreshes and centre
point / radius changes (a park keeps its Google identity even if it drops
in or out of the configured search area).

Photos are *not* stored here — only their filenames. The image bytes live
on disk under `<config>/park_visits_photos/<place_id>/`, because this
store is loaded into memory and rewritten in full on every save; a few
base64 photos would bloat it badly.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import PARKS_CACHE_KEY_TEMPLATE, STORAGE_KEY_TEMPLATE, STORAGE_VERSION


@dataclass
class Review:
    """A single stored review for one park.

    ``park_name`` is denormalised deliberately: a park can drop out of the
    tracked list (rating shifts, radius changes) while its review and photos
    live on, and the gallery still needs something to label them with.
    """

    rating: float
    liked: str = ""
    disliked: str = ""
    note: str = ""
    photos: list[str] = field(default_factory=list)
    reviewed_at: str = ""
    park_name: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Review:
        """Build from stored JSON, tolerating records written by older versions.

        v1 reviews only had rating/note/reviewed_at. Reading them with
        cls(**data) would work, but any future field added here would break
        old records, so pull fields explicitly and default what's missing.
        """
        return cls(
            rating=data.get("rating", 0),
            liked=data.get("liked", ""),
            disliked=data.get("disliked", ""),
            note=data.get("note", ""),
            photos=list(data.get("photos", [])),
            reviewed_at=data.get("reviewed_at", ""),
            park_name=data.get("park_name", ""),
        )


class ParkReviewStore:
    """Loads/saves {place_id: Review} to a per-entry HA storage file."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_TEMPLATE.format(entry_id=entry_id)
        )
        self._reviews: dict[str, Review] = {}

    async def async_load(self) -> None:
        """Load reviews from disk (call once during entry setup)."""
        raw: dict[str, Any] | None = await self._store.async_load()
        if raw:
            self._reviews = {
                place_id: Review.from_dict(data) for place_id, data in raw.items()
            }

    def get(self, place_id: str) -> Review | None:
        """Return the stored review for a park, if any."""
        return self._reviews.get(place_id)

    def all_reviews(self) -> dict[str, Review]:
        """Return all stored reviews, keyed by place_id."""
        return dict(self._reviews)

    async def async_set_review(
        self,
        place_id: str,
        rating: float,
        liked: str = "",
        disliked: str = "",
        note: str = "",
        photos: list[str] | None = None,
        park_name: str = "",
    ) -> Review:
        """Record (or overwrite) a review for a park and persist it.

        Photos default to whatever is already stored rather than being
        cleared, so editing a rating from a form that didn't re-upload the
        images doesn't silently drop them.
        """
        existing = self._reviews.get(place_id)
        review = Review(
            rating=rating,
            liked=liked,
            disliked=disliked,
            note=note,
            photos=list(photos) if photos is not None else (existing.photos if existing else []),
            reviewed_at=datetime.now(timezone.utc).isoformat(),
            park_name=park_name or (existing.park_name if existing else ""),
        )
        self._reviews[place_id] = review
        await self._async_save()
        return review

    async def async_delete_review(self, place_id: str) -> list[str]:
        """Forget a park's review entirely, returning the photo filenames.

        The caller deletes the files: this store only ever tracks names.
        """
        review = self._reviews.pop(place_id, None)
        if review is None:
            return []
        await self._async_save()
        return list(review.photos)

    async def async_add_photo(
        self, place_id: str, filename: str, park_name: str = ""
    ) -> Review:
        """Attach an uploaded photo to a park, creating a stub review if needed.

        A photo can be uploaded before the rating is submitted (the form
        uploads as soon as a file is picked), so this must not require an
        existing review.
        """
        review = self._reviews.get(place_id)
        if review is None:
            review = Review(rating=0, reviewed_at="", park_name=park_name)
            self._reviews[place_id] = review
        elif park_name and not review.park_name:
            review.park_name = park_name
        if filename not in review.photos:
            review.photos.append(filename)
        await self._async_save()
        return review

    async def async_remove_photo(self, place_id: str, filename: str) -> None:
        """Detach a photo from a park's review."""
        review = self._reviews.get(place_id)
        if review and filename in review.photos:
            review.photos.remove(filename)
            await self._async_save()

    async def _async_save(self) -> None:
        await self._store.async_save(
            {place_id: asdict(r) for place_id, r in self._reviews.items()}
        )


class ParkListCache:
    """Persists the last fetched park list so a restart costs no API quota.

    Without this, Home Assistant's normal "refresh on setup" behaviour would
    spend a full (paid) tiled Google search every time it restarts, which
    defeats the point of the manual refresh button. The search parameters are
    stored alongside the data: if the centre point, radius or park count has
    changed, the cache is treated as stale and a real fetch happens instead.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store = Store(
            hass, STORAGE_VERSION, PARKS_CACHE_KEY_TEMPLATE.format(entry_id=entry_id)
        )

    async def async_load(self, fingerprint: str) -> list[dict[str, Any]] | None:
        """Return cached parks if they were fetched with these same settings."""
        raw = await self._store.async_load()
        if not raw or raw.get("fingerprint") != fingerprint:
            return None
        parks = raw.get("parks")
        return parks if isinstance(parks, list) and parks else None

    async def async_save(self, fingerprint: str, parks: list[dict[str, Any]]) -> None:
        await self._store.async_save({"fingerprint": fingerprint, "parks": parks})
