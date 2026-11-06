"""Small dependency-free geographical helpers.

Walking length is approximated from great-circle distance when no pedestrian
routing provider is configured. A multiplier is only an estimate, not a route.
"""
import math

WALKING_SPEED_M_PER_SECOND = 1.25  # ~4.5 km/h
WALKING_DETOUR_FACTOR = 1.28


def distance_metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000
    a1, a2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(a1)*math.cos(a2)*math.sin(dlon/2)**2
    return 2*radius*math.asin(min(1, math.sqrt(a)))


def walking_minutes(distance_m: float) -> int:
    """Conservative approximate time, rounded up to whole minutes."""
    return max(0, math.ceil(distance_m * WALKING_DETOUR_FACTOR / WALKING_SPEED_M_PER_SECOND / 60))


def valid_latlon(lat: float, lon: float) -> bool:
    return math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180


def oxford_area(lat: float, lon: float) -> bool:
    return 51.58 <= lat <= 51.97 and -1.59 <= lon <= -0.94
