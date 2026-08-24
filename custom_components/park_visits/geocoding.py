"""Resolve a free-text location (a suburb, city or address) to coordinates.

Uses the Google Places API (New) Text Search endpoint rather than the
separate Geocoding API so no extra Google API needs to be enabled beyond
the "Places API (New)" the rest of the integration already requires.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    GEOCODE_API_URL,
    PLACES_ADD_FIELD_MASK,
    PLACES_API_DETAILS_URL,
    GEOCODE_FIELD_MASK,
    MAX_SEARCH_RESULTS,
    PLACES_API_NOISE_TYPES,
    PLACES_SEARCH_FIELD_MASK,
)

_LOGGER = logging.getLogger(__name__)


class GeocodeError(Exception):
    """Base error for location resolution failures."""


class GeocodeAuthFailed(GeocodeError):
    """The API key was rejected."""


class GeocodeNotFound(GeocodeError):
    """No place matched the given text."""


class GeocodeConnectionError(GeocodeError):
    """Couldn't reach Google, or it returned an unexpected error."""


@dataclass
class GeocodeResult:
    """A resolved location."""

    latitude: float
    longitude: float
    formatted_address: str


async def async_geocode_location(hass: HomeAssistant, api_key: str, query: str) -> GeocodeResult:
    """Resolve free text (e.g. "Cornubia QLD" or "123 Example St, Brisbane") to a location."""
    session = async_get_clientsession(hass)
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": GEOCODE_FIELD_MASK,
    }
    try:
        async with session.post(
            GEOCODE_API_URL,
            json={"textQuery": query},
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status in (401, 403):
                raise GeocodeAuthFailed(f"Google rejected the request ({response.status})")
            if response.status != 200:
                text = await response.text()
                raise GeocodeConnectionError(f"Google Places API error {response.status}: {text[:200]}")
            payload = await response.json()
    except aiohttp.ClientError as err:
        raise GeocodeConnectionError(str(err)) from err

    places = payload.get("places") or []
    if not places:
        raise GeocodeNotFound(query)

    place = places[0]
    location = place.get("location") or {}
    latitude, longitude = location.get("latitude"), location.get("longitude")
    if latitude is None or longitude is None:
        raise GeocodeNotFound(query)

    formatted_address = (
        place.get("formattedAddress")
        or place.get("displayName", {}).get("text")
        or query
    )
    return GeocodeResult(
        latitude=latitude, longitude=longitude, formatted_address=formatted_address
    )


@dataclass
class PlaceCandidate:
    """One search hit, enough to add a park by hand without a second call."""

    place_id: str
    name: str
    address: str
    latitude: float
    longitude: float
    categories: list[str]
    google_maps_uri: str | None
    # Only populated when the place was resolved by id via Place Details —
    # the search mask deliberately doesn't pay for these.
    rating: float | None = None
    rating_count: int = 0


async def async_search_places(
    hass: HomeAssistant, api_key: str, query: str, limit: int = MAX_SEARCH_RESULTS
) -> list[PlaceCandidate]:
    """Search Google for places matching free text, for adding a park by hand.

    Uses the same Text Search endpoint as async_geocode_location but asks for
    several results and a slightly wider field mask — still the cheap one:
    no rating or userRatingCount, which would move the request to a pricier
    SKU (see const.PLACES_SEARCH_FIELD_MASK). A park added this way has no
    Google rating until it is opened and Place Details fills one in.

    Returns [] rather than raising when nothing matches; the caller is a
    search box, where "no results" is an ordinary outcome, not an error.
    """
    session = async_get_clientsession(hass)
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": PLACES_SEARCH_FIELD_MASK,
    }
    try:
        async with session.post(
            GEOCODE_API_URL,
            json={"textQuery": query, "maxResultCount": limit},
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status in (401, 403):
                raise GeocodeAuthFailed(f"Google rejected the request ({response.status})")
            if response.status != 200:
                text = await response.text()
                raise GeocodeConnectionError(
                    f"Google Places API error {response.status}: {text[:200]}"
                )
            payload = await response.json()
    except aiohttp.ClientError as err:
        raise GeocodeConnectionError(str(err)) from err

    results: list[PlaceCandidate] = []
    for place in (payload.get("places") or [])[:limit]:
        location = place.get("location") or {}
        latitude, longitude = location.get("latitude"), location.get("longitude")
        if not place.get("id") or latitude is None or longitude is None:
            continue
        results.append(
            PlaceCandidate(
                place_id=place["id"],
                name=(place.get("displayName") or {}).get("text") or "Unnamed place",
                address=place.get("formattedAddress", ""),
                latitude=latitude,
                longitude=longitude,
                # Same presentation as the nearby search builds, so a manually
                # added park's categories look like every other park's.
                categories=[
                    t.replace("_", " ").title()
                    for t in place.get("types", [])
                    if t not in PLACES_API_NOISE_TYPES
                ],
                google_maps_uri=place.get("googleMapsUri"),
            )
        )
    return results


async def async_place_details(
    hass: HomeAssistant, api_key: str, place_id: str
) -> PlaceCandidate:
    """Resolve a place_id to a place.

    Text Search matches names and addresses, so it can never find a place by
    id — this is the endpoint for that. The field mask leaves out reviews and
    photos (what makes the card's details call expensive) but keeps the
    rating, so a park added this way is immediately sortable.
    """
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            PLACES_API_DETAILS_URL.format(place_id=place_id),
            headers={
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": PLACES_ADD_FIELD_MASK,
            },
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status in (401, 403):
                raise GeocodeAuthFailed(f"Google rejected the request ({response.status})")
            if response.status == 404:
                raise GeocodeNotFound(place_id)
            if response.status != 200:
                text = await response.text()
                raise GeocodeConnectionError(
                    f"Google Places API error {response.status}: {text[:200]}"
                )
            place = await response.json()
    except aiohttp.ClientError as err:
        raise GeocodeConnectionError(str(err)) from err

    location = place.get("location") or {}
    latitude, longitude = location.get("latitude"), location.get("longitude")
    if latitude is None or longitude is None:
        raise GeocodeNotFound(place_id)

    return PlaceCandidate(
        place_id=place.get("id") or place_id,
        name=(place.get("displayName") or {}).get("text") or "Unnamed place",
        address=place.get("formattedAddress", ""),
        latitude=latitude,
        longitude=longitude,
        categories=[
            t.replace("_", " ").title()
            for t in place.get("types", [])
            if t not in PLACES_API_NOISE_TYPES
        ],
        google_maps_uri=place.get("googleMapsUri"),
        rating=place.get("rating"),
        rating_count=place.get("userRatingCount", 0),
    )
