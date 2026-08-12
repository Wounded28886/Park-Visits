"""Persistent storage for our own park ratings/notes.

Keyed by Google place_id so a review survives dataset refreshes and centre
point / radius changes (a park keeps its Google identity even if it drops
in or out of the configured search area).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY_TEMPLATE, STORAGE_VERSION


@dataclass
class Review:
    """A single stored review for one park."""

    rating: float
    note: str
    reviewed_at: str


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
                place_id: Review(**data) for place_id, data in raw.items()
            }

    def get(self, place_id: str) -> Review | None:
        """Return the stored review for a park, if any."""
        return self._reviews.get(place_id)

    def all_reviews(self) -> dict[str, Review]:
        """Return all stored reviews, keyed by place_id."""
        return dict(self._reviews)

    async def async_set_review(self, place_id: str, rating: float, note: str) -> Review:
        """Record (or overwrite) a review for a park and persist it."""
        review = Review(
            rating=rating,
            note=note,
            reviewed_at=datetime.now(timezone.utc).isoformat(),
        )
        self._reviews[place_id] = review
        await self._store.async_save(
            {place_id: asdict(r) for place_id, r in self._reviews.items()}
        )
        return review
