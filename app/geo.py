"""Geospatial helpers: haversine distance and a simple ETA estimate."""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in kilometres between two points.

    Uses the haversine formula over a spherical-earth approximation.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    c = 2 * math.asin(min(1.0, math.sqrt(a)))
    return EARTH_RADIUS_KM * c


def eta_minutes(distance_km: float, speed_kmh: float) -> float:
    """Return a naive ETA in minutes for travelling ``distance_km`` at ``speed_kmh``.

    Raises:
        ValueError: if ``speed_kmh`` is not positive.
    """
    if speed_kmh <= 0:
        raise ValueError("speed_kmh must be positive")
    return (distance_km / speed_kmh) * 60.0
