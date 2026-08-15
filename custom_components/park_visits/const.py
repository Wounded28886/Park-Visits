"""Constants for the Park Visits integration."""
from __future__ import annotations

DOMAIN = "park_visits"
DEFAULT_NAME = "Park Visits"

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
# Optional: point at an Immich server to show a park's photos straight from
# your own library instead of uploading copies into Home Assistant.
CONF_IMMICH_URL = "immich_url"
CONF_IMMICH_API_KEY = "immich_api_key"
# Free text entered by the user (a suburb, city or address) — resolved to
# CONF_LOCATION_NAME + latitude/longitude via Google Places Text Search
# during the config/options flow, not typed in as coordinates.
CONF_LOCATION = "location"
CONF_LOCATION_NAME = "location_name"
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
# One attribute per rating "column" a review can carry, plus the computed
# family average. kids_rating is the only one that's required when writing
# a review — everything else is optional.
ATTR_OUR_KIDS_RATING = "our_kids_rating"
ATTR_OUR_MUMS_RATING = "our_mums_rating"
ATTR_OUR_DADS_RATING = "our_dads_rating"
ATTR_OUR_PLAYGROUND_RATING = "our_playground_rating"
ATTR_OUR_SCENERY_RATING = "our_scenery_rating"
ATTR_OUR_WILDLIFE_RATING = "our_wildlife_rating"
ATTR_OUR_FACILITIES_RATING = "our_facilities_rating"
ATTR_OUR_PARKING_RATING = "our_parking_rating"
ATTR_OUR_OVERALL_RATING = "our_overall_rating"
ATTR_OUR_NOTE = "our_note"
ATTR_OUR_VISIT_DATE = "our_visit_date"

# park_visits.rate_park service
SERVICE_RATE_PARK = "rate_park"
SERVICE_DELETE_REVIEW = "delete_review"
SERVICE_DELETE_PHOTO = "delete_photo"
SERVICE_SET_NEXT_PARK = "set_next_park"
SERVICE_CLEAR_NEXT_PARK = "clear_next_park"
SERVICE_ATTR_FILENAME = "filename"
SERVICE_ATTR_PLACE_ID = "place_id"
SERVICE_ATTR_KIDS_RATING = "kids_rating"
SERVICE_ATTR_MUMS_RATING = "mums_rating"
SERVICE_ATTR_DADS_RATING = "dads_rating"
SERVICE_ATTR_PLAYGROUND_RATING = "playground_rating"
SERVICE_ATTR_SCENERY_RATING = "scenery_rating"
SERVICE_ATTR_WILDLIFE_RATING = "wildlife_rating"
SERVICE_ATTR_FACILITIES_RATING = "facilities_rating"
SERVICE_ATTR_PARKING_RATING = "parking_rating"
SERVICE_ATTR_VISIT_DATE = "visit_date"
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
URL_IMMICH_TAGS = "/api/park_visits/immich/tags"
URL_IMMICH_THUMB = "/api/park_visits/immich/thumb/{asset_id}"

# Immich
IMMICH_TAG_KEY_TEMPLATE = f"{DOMAIN}_immich_tags_{{entry_id}}"
IMMICH_MAX_ASSETS = 24
IMMICH_TIMEOUT = 20
SERVICE_SET_PARK_TAG = "set_park_tag"
SERVICE_CLEAR_PARK_TAG = "clear_park_tag"
SERVICE_ATTR_TAG_ID = "tag_id"

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

# Resolves a free-text location (a suburb, city or address) to coordinates,
# used only during the config/options flow — not on every refresh.
GEOCODE_API_URL = "https://places.googleapis.com/v1/places:searchText"
GEOCODE_FIELD_MASK = "places.location,places.formattedAddress,places.displayName"
