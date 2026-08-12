"""Geo helpers for the Park Visits integration."""
from __future__ import annotations

from math import asin, atan2, cos, degrees, radians, sin, sqrt

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance between two points in kilometres."""
    lat1_r, lon1_r, lat2_r, lon2_r = (radians(v) for v in (lat1, lon1, lat2, lon2))
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = sin(dlat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def destination_point(
    lat: float, lon: float, distance_km: float, bearing_deg: float
) -> tuple[float, float]:
    """Return the point `distance_km` from (lat, lon) along `bearing_deg` (0=N, 90=E)."""
    lat_r, lon_r, bearing_r = radians(lat), radians(lon), radians(bearing_deg)
    angular_distance = distance_km / EARTH_RADIUS_KM

    dest_lat_r = asin(
        sin(lat_r) * cos(angular_distance) + cos(lat_r) * sin(angular_distance) * cos(bearing_r)
    )
    dest_lon_r = lon_r + atan2(
        sin(bearing_r) * sin(angular_distance) * cos(lat_r),
        cos(angular_distance) - sin(lat_r) * sin(dest_lat_r),
    )
    return degrees(dest_lat_r), degrees(dest_lon_r)
