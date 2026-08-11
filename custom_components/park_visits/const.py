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
MAX_RADIUS_KM = 500
MIN_MAX_PARKS = 1
MAX_MAX_PARKS = 200

CONF_RADIUS_KM = "radius_km"
CONF_MAX_PARKS = "max_parks"

# Value used for the geo_location entity "source" attribute so dashboard
# cards (map + list) can filter on it.
SOURCE = DOMAIN

ATTRIBUTION = (
    "Park list curated from public sources (OpenStreetMap, Wikipedia, "
    "Queensland Parks & Wildlife Service and local council park listings). "
    "Popularity ranking is a best-effort editorial curation, not a live API score."
)

ATTR_RANK = "rank"
ATTR_CATEGORY = "category"
ATTR_LOCALITY = "locality"
ATTR_DESCRIPTION = "description"
