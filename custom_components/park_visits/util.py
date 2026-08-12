"""Helpers for the Park Visits integration."""
from __future__ import annotations

import json
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).parent / "data" / "parks.json"

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance between two points in kilometres."""
    lat1_r, lon1_r, lat2_r, lon2_r = (radians(v) for v in (lat1, lon1, lat2, lon2))
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = sin(dlat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def load_parks() -> list[dict[str, Any]]:
    """Load the bundled curated parks dataset."""
    with DATA_FILE.open(encoding="utf-8") as parks_file:
        return json.load(parks_file)
