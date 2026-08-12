"""Constants for the Park Visits integration."""
from __future__ import annotations

DOMAIN = "park_visits"
DEFAULT_NAME = "Park Visits"

# Cornubia, City of Logan, Queensland, Australia
DEFAULT_LATITUDE = -27.6599
DEFAULT_LONGITUDE = 153.2138

DEFAULT_RADIUS_KM = 100
DEFAULT_MAX_PARKS = 100
MIN_RADIUS_KM = 1
MAX_RADIUS_KM = 300
MIN_MAX_PARKS = 1
MAX_MAX_PARKS = 200

CONF_API_KEY = "api_key"
CONF_RADIUS_KM = "radius_km"
CONF_MAX_PARKS = "max_parks"

# Value used for the geo_location entity "source" attribute so dashboard
# cards (map + list) can filter on it.
SOURCE = DOMAIN

ATTRIBUTION = "Places data © Google. Ratings and reviews are from Google Maps users."

ATTR_RANK = "rank"
ATTR_CATEGORIES = "categories"
ATTR_ADDRESS = "address"
ATTR_PLACE_ID = "place_id"
ATTR_RATING = "rating"
ATTR_RATING_COUNT = "rating_count"
ATTR_GOOGLE_MAPS_URI = "google_maps_uri"
ATTR_DISTANCE_KM = "distance_km"
ATTR_OUR_RATING = "our_rating"
ATTR_OUR_NOTE = "our_note"
ATTR_OUR_REVIEWED_AT = "our_reviewed_at"

# park_visits.rate_park service
SERVICE_RATE_PARK = "rate_park"
SERVICE_ATTR_PLACE_ID = "place_id"
SERVICE_ATTR_RATING = "rating"
SERVICE_ATTR_NOTE = "note"
MIN_OUR_RATING = 0
MAX_OUR_RATING = 10

STORAGE_VERSION = 1
STORAGE_KEY_TEMPLATE = f"{DOMAIN}_reviews_{{entry_id}}"

# Google Places API (New)
PLACES_API_BASE_URL = "https://places.googleapis.com/v1/places:searchNearby"
PLACES_API_INCLUDED_TYPES = ["park"]
PLACES_API_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.location",
        "places.types",
        "places.rating",
        "places.userRatingCount",
        "places.formattedAddress",
        "places.googleMapsUri",
    ]
)
# Types Google attaches to nearly every place; not useful as a displayed category.
PLACES_API_NOISE_TYPES = {"point_of_interest", "establishment"}
# Google's Nearby Search hard caps the search radius at 50km per request.
PLACES_API_MAX_TILE_RADIUS_KM = 50
PLACES_API_MAX_RESULTS_PER_TILE = 20
