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
