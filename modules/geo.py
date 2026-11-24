"""Small geography helper shared by the modules (kept separate so importing it is instant)."""
import math


def haversine_m(lat1, lon1, lat2, lon2):
    """Straight-line distance in metres between two latitude/longitude points."""
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# Centres of the 12 synthetic wards (same layout the dataset generator uses).
WARD_CENTRES = {w + 1: (13.00 + (w // 4) * 0.012, 80.20 + (w % 4) * 0.012) for w in range(12)}


def nearest_ward(lat, lon):
    return min(WARD_CENTRES, key=lambda w: haversine_m(lat, lon, *WARD_CENTRES[w]))


# The area CivicSense serves (covers every ward and the whole road graph). A complaint outside it is rejected.
SERVICE_AREA = {"lat_min": 12.990, "lat_max": 13.050, "lon_min": 80.190, "lon_max": 80.250}


def in_service_area(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return False
    a = SERVICE_AREA
    return a["lat_min"] <= lat <= a["lat_max"] and a["lon_min"] <= lon <= a["lon_max"]
