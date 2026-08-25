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

from .const import (
    HIDDEN_KEY_TEMPLATE,
    IMMICH_TAG_KEY_TEMPLATE,
    MANUAL_KEY_TEMPLATE,
    PARKS_CACHE_KEY_TEMPLATE,
    PLAN_KEY_TEMPLATE,
    STORAGE_KEY_TEMPLATE,
    STORAGE_VERSION,
)


@dataclass
class Review:
    """A single stored review for one park.

    ``park_name`` is denormalised deliberately: a park can drop out of the
    tracked list (rating shifts, radius changes) while its review and photos
    live on, and the gallery still needs something to label them with.

    ``person_ratings`` holds one optional 0-10 rating per configured person
    (see const.CONF_PEOPLE), keyed by util.slugify_person(name) rather than
    the raw name — that way editing someone's name in the options doesn't
    orphan their history, only replacing/removing it does. Only people who
    were actually rated appear here; there is no fixed "required" person.
    ``overall_rating`` is deliberately not a stored field — it's the
    average of whichever person_ratings are present, computed fresh so it
    can never drift out of sync with the values it's derived from.
    """

    person_ratings: dict[str, float] = field(default_factory=dict)
    playground_rating: float | None = None
    scenery_rating: float | None = None
    wildlife_rating: float | None = None
    facilities_rating: float | None = None
    parking_rating: float | None = None
    liked: str = ""
    disliked: str = ""
    note: str = ""
    photos: list[str] = field(default_factory=list)
    # ISO date "YYYY-MM-DD" the visit actually happened, chosen by whoever
    # wrote the review (defaults to today client-side, but can be back-dated).
    # Empty string means "not reviewed yet" (e.g. a stub created by an
    # early photo upload before the rating form was submitted). This is the
    # only thing a review actually requires.
    visit_date: str = ""
    park_name: str = ""

    @property
    def overall_rating(self) -> float | None:
        """Average of whichever people were rated this visit, or None if none were."""
        values = list(self.person_ratings.values())
        if not values:
            return None
        return round(sum(values) / len(values), 2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Review:
        """Build from stored JSON, tolerating records written by older versions.

        Three schema generations to bridge:
        - Current: ``person_ratings`` is a {person_id: rating} dict.
        - 1.2-1.6: fixed ``kids_rating``/``mums_rating``/``dads_rating``
          fields (configurable people replaced these) — migrated onto the
          default people list's ids ("kids"/"mum"/"dad", which is exactly
          what slugify_person(name) gives for the default ["Kids", "Mum",
          "Dad"], so this lines up with an unconfigured install automatically).
        - Pre-1.2: a single ``rating`` (0-10) and a full ISO ``reviewed_at``
          timestamp — ``rating`` seeds person_ratings["kids"], and the date
          portion of ``reviewed_at`` seeds ``visit_date``.
        Aspect ratings and everything else are unaffected by this and just
        default to blank on older records.
        """
        if "person_ratings" in data:
            raw_ratings = data.get("person_ratings") or {}
            person_ratings = {k: v for k, v in raw_ratings.items() if v is not None}
            visit_date = data.get("visit_date", "")
        elif "kids_rating" in data or "visit_date" in data:
            person_ratings = {}
            for person_id, legacy_key in (
                ("kids", "kids_rating"),
                ("mum", "mums_rating"),
                ("dad", "dads_rating"),
            ):
                value = data.get(legacy_key)
                if value is not None:
                    person_ratings[person_id] = value
            visit_date = data.get("visit_date", "")
        else:
            legacy_rating = data.get("rating")
            person_ratings = {"kids": legacy_rating} if legacy_rating is not None else {}
            legacy_reviewed_at = data.get("reviewed_at") or ""
            visit_date = legacy_reviewed_at[:10] if legacy_reviewed_at else ""

        return cls(
            person_ratings=person_ratings,
            playground_rating=data.get("playground_rating"),
            scenery_rating=data.get("scenery_rating"),
            wildlife_rating=data.get("wildlife_rating"),
            facilities_rating=data.get("facilities_rating"),
            parking_rating=data.get("parking_rating"),
            liked=data.get("liked", ""),
            disliked=data.get("disliked", ""),
            note=data.get("note", ""),
            photos=list(data.get("photos", [])),
            visit_date=visit_date,
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
        person_ratings: dict[str, float],
        visit_date: str,
        playground_rating: float | None = None,
        scenery_rating: float | None = None,
        wildlife_rating: float | None = None,
        facilities_rating: float | None = None,
        parking_rating: float | None = None,
        liked: str = "",
        disliked: str = "",
        note: str = "",
        photos: list[str] | None = None,
        park_name: str = "",
    ) -> Review:
        """Record (or overwrite) a review for a park and persist it.

        Photos default to whatever is already stored rather than being
        cleared, so editing a review from a form that didn't re-upload the
        images doesn't silently drop them.
        """
        existing = self._reviews.get(place_id)
        review = Review(
            person_ratings=dict(person_ratings or {}),
            playground_rating=playground_rating,
            scenery_rating=scenery_rating,
            wildlife_rating=wildlife_rating,
            facilities_rating=facilities_rating,
            parking_rating=parking_rating,
            liked=liked,
            disliked=disliked,
            note=note,
            photos=list(photos) if photos is not None else (existing.photos if existing else []),
            visit_date=visit_date,
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
            review = Review(park_name=park_name)
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


class ParkPlanStore:
    """Remembers which park we've decided to visit next.

    Kept apart from the review store: it's a single pointer rather than a
    per-park record, and it changes on a different rhythm.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store = Store(
            hass, STORAGE_VERSION, PLAN_KEY_TEMPLATE.format(entry_id=entry_id)
        )
        self._next: dict[str, Any] | None = None

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        if raw and raw.get("place_id"):
            self._next = raw

    @property
    def next_park(self) -> dict[str, Any] | None:
        """{'place_id', 'park_name', 'set_at'} for the planned park, if any."""
        return dict(self._next) if self._next else None

    async def async_set_next(self, place_id: str, park_name: str = "") -> None:
        self._next = {
            "place_id": place_id,
            "park_name": park_name,
            "set_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._store.async_save(self._next)

    async def async_clear_next(self) -> None:
        self._next = None
        await self._store.async_save({})


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


class ParkTagStore:
    """Maps a park to the Immich tag whose photos belong to it.

    Stored per place_id so the link survives a park dropping out of the
    tracked list and coming back. The tag *name* is kept alongside its id
    purely so the UI can label things when Immich is unreachable.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store = Store(
            hass, STORAGE_VERSION, IMMICH_TAG_KEY_TEMPLATE.format(entry_id=entry_id)
        )
        self._tags: dict[str, dict[str, str]] = {}

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        if raw:
            self._tags = {
                place_id: value
                for place_id, value in raw.items()
                if isinstance(value, dict) and value.get("tag_id")
            }

    def get(self, place_id: str) -> dict[str, str] | None:
        tag = self._tags.get(place_id)
        return dict(tag) if tag else None

    def all_tags(self) -> dict[str, dict[str, str]]:
        return {place_id: dict(tag) for place_id, tag in self._tags.items()}

    async def async_set(self, place_id: str, tag_id: str, tag_name: str = "") -> None:
        self._tags[place_id] = {"tag_id": tag_id, "tag_name": tag_name}
        await self._store.async_save(self._tags)

    async def async_clear(self, place_id: str) -> None:
        if self._tags.pop(place_id, None) is not None:
            await self._store.async_save(self._tags)


class ManualParkStore:
    """Parks added by hand, which the area search would never return.

    Two reasons a park needs this: it sits outside the configured radius, or
    it has fewer than MIN_RATING_COUNT ratings and is filtered out of the
    ranked list. Either way it must survive a refresh, so the fields Google
    gave us at add time are stored here rather than re-fetched — adding a
    park costs one Text Search, ever.

    ``rating``/``rating_count`` start as None/0 because the search that finds
    these parks deliberately doesn't pay for them; async_set_rating fills
    them in from the Place Details call that happens when the park is first
    opened.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store = Store(
            hass, STORAGE_VERSION, MANUAL_KEY_TEMPLATE.format(entry_id=entry_id)
        )
        self._parks: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        if raw:
            self._parks = {
                place_id: park
                for place_id, park in raw.items()
                if isinstance(park, dict) and park.get("name")
            }

    def all_parks(self) -> dict[str, dict[str, Any]]:
        return {place_id: dict(park) for place_id, park in self._parks.items()}

    def has(self, place_id: str) -> bool:
        return place_id in self._parks

    async def async_add(
        self,
        place_id: str,
        name: str,
        address: str,
        latitude: float,
        longitude: float,
        categories: list[str] | None = None,
        google_maps_uri: str | None = None,
        rating: float | None = None,
        rating_count: int = 0,
    ) -> None:
        """Add (or refresh the details of) a manually added park.

        A rating is optional because it depends how the park was found: an
        id resolves via Place Details, which returns one, while a text search
        deliberately doesn't pay for it.
        """
        existing = self._parks.get(place_id) or {}
        self._parks[place_id] = {
            "name": name,
            "address": address,
            "latitude": latitude,
            "longitude": longitude,
            "categories": list(categories or []),
            "google_maps_uri": google_maps_uri,
            # A freshly supplied rating wins; otherwise keep whatever was
            # already learned, so a re-add never throws one away.
            "rating": rating if rating is not None else existing.get("rating"),
            "rating_count": rating_count or existing.get("rating_count", 0),
            "added_at": existing.get("added_at") or datetime.now(timezone.utc).isoformat(),
        }
        await self._store.async_save(self._parks)

    async def async_set_rating(
        self, place_id: str, rating: float | None, rating_count: int
    ) -> bool:
        """Record the Google rating learned from Place Details.

        Returns True when something actually changed, so the caller only
        refreshes entities when there is a reason to.
        """
        park = self._parks.get(place_id)
        if park is None:
            return False
        if park.get("rating") == rating and park.get("rating_count") == rating_count:
            return False
        park["rating"] = rating
        park["rating_count"] = rating_count
        await self._store.async_save(self._parks)
        return True

    async def async_remove(self, place_id: str) -> bool:
        """Stop tracking a manually added park. Its review and photos remain.

        Those are keyed by place_id elsewhere, so re-adding the park later
        reunites it with everything written about it.
        """
        if self._parks.pop(place_id, None) is None:
            return False
        await self._store.async_save(self._parks)
        return True


class HiddenParkStore:
    """Parks removed from the list by hand.

    Removal can't just drop a park: the ranked search returns whatever it
    returns, so anything deleted would be back after the next refresh. This
    records the decision instead, and the coordinator filters against it.

    The park's name is kept alongside its id purely so removed parks can be
    listed for restoring — by then the park isn't in the tracked list any
    more, so there's nowhere else to read a name from.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store = Store(
            hass, STORAGE_VERSION, HIDDEN_KEY_TEMPLATE.format(entry_id=entry_id)
        )
        self._hidden: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        if raw:
            self._hidden = {
                place_id: value
                for place_id, value in raw.items()
                if isinstance(value, dict)
            }

    def is_hidden(self, place_id: str) -> bool:
        return place_id in self._hidden

    def all_hidden(self) -> dict[str, dict[str, Any]]:
        return {place_id: dict(value) for place_id, value in self._hidden.items()}

    async def async_hide(self, place_id: str, name: str = "") -> bool:
        """Remove a park from the list. True if it wasn't already removed."""
        if place_id in self._hidden:
            return False
        self._hidden[place_id] = {
            "name": name,
            "hidden_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._store.async_save(self._hidden)
        return True

    async def async_unhide(self, place_id: str) -> bool:
        """Put a park back. True if it was actually removed beforehand."""
        if self._hidden.pop(place_id, None) is None:
            return False
        await self._store.async_save(self._hidden)
        return True
