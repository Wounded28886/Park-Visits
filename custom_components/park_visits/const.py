"""Constants for the Park Visits integration."""
from __future__ import annotations

DOMAIN = "park_visits"
DEFAULT_NAME = "Park Visits"

# Cornubia, City of Logan, Queensland, Australia
DEFAULT_LATITUDE = -27.6599
DEFAULT_LONGITUDE = 153.2138

DEFAULT_RADIUS_KM = 100
DEFAULT_MAX_PARKS = 100

# Parks with only a handful of Google ratings aren't meaningfully "top rated"
# — a lone 5.0 review would otherwise outrank a genuinely popular park. Places
# below this many ratings are left out of the list entirely.
MIN_RATING_COUNT = 5
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
SERVICE_DELETE_REVIEW = "delete_review"
SERVICE_DELETE_PHOTO = "delete_photo"
SERVICE_SET_NEXT_PARK = "set_next_park"
SERVICE_CLEAR_NEXT_PARK = "clear_next_park"
SERVICE_ATTR_FILENAME = "filename"
SERVICE_ATTR_PLACE_ID = "place_id"
SERVICE_ATTR_RATING = "rating"
SERVICE_ATTR_NOTE = "note"
SERVICE_ATTR_LIKED = "liked"
SERVICE_ATTR_DISLIKED = "disliked"
MIN_OUR_RATING = 0
MAX_OUR_RATING = 10

ATTR_OUR_LIKED = "our_liked"
ATTR_OUR_DISLIKED = "our_disliked"
ATTR_OUR_PHOTO_COUNT = "our_photo_count"

# Our own uploaded photos live on disk, not in the review store.
PHOTO_DIR_NAME = "park_visits_photos"
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
ALLOWED_PHOTO_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

# HTTP endpoints served by the integration (see views.py).
URL_DETAILS = "/api/park_visits/details/{place_id}"
URL_GOOGLE_PHOTO = "/api/park_visits/google_photo/{place_id}/{index}"
URL_OUR_PHOTO = "/api/park_visits/photo/{place_id}/{filename}"
URL_UPLOAD = "/api/park_visits/upload/{place_id}"

# Cards locate these sensors by attribute rather than entity_id, which Home
# Assistant may suffix or a user may rename.
ATTR_ROLE = "park_visits_role"
ROLE_NEXT_PARK = "next_park"
ROLE_LAST_VISITED = "last_visited"
ATTR_SET_AT = "set_at"

STORAGE_VERSION = 1
STORAGE_KEY_TEMPLATE = f"{DOMAIN}_reviews_{{entry_id}}"
PLAN_KEY_TEMPLATE = f"{DOMAIN}_plan_{{entry_id}}"
# The fetched park list is cached to disk so a Home Assistant restart doesn't
# silently spend a full (paid) Google search just to repopulate entities.
PARKS_CACHE_KEY_TEMPLATE = f"{DOMAIN}_parks_{{entry_id}}"

# Google Places API (New)
PLACES_API_BASE_URL = "https://places.googleapis.com/v1/places:searchNearby"
PLACES_API_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
PLACES_API_PHOTO_URL = "https://places.googleapis.com/v1/{photo_name}/media"

# Reviews and photos are NOT requested in the bulk Nearby Search: they sit
# on Google's pricier SKUs, so pulling them for every tracked park on each
# refresh would cost orders of magnitude more than the search itself. They
# are fetched per-park via Place Details only when a park is opened, and
# cached for DETAILS_CACHE_HOURS so reopening one is free.
PLACES_API_DETAILS_FIELD_MASK = ",".join(
    [
        "id",
        "displayName",
        "formattedAddress",
        "rating",
        "userRatingCount",
        "googleMapsUri",
        "websiteUri",
        "nationalPhoneNumber",
        "currentOpeningHours.weekdayDescriptions",
        "editorialSummary",
        "reviews",
        "photos",
    ]
)
DETAILS_CACHE_HOURS = 24
MAX_GOOGLE_PHOTOS = 6
GOOGLE_PHOTO_MAX_WIDTH = 800
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
