"""Schools, hospitals and busy public places, and which of them a complaint is near.

Schools and hospitals are 'sensitive': the people there are children, patients and their families.
Markets, bus stands, stations, temples and parks are 'busy public places': crowds pass every day.
The rule engine (rules/rules.yaml) decides what being near each kind means for priority.
"""
import os

import yaml

try:
    from modules.geo import SERVICE_AREA, haversine_m
except ImportError:                                   # when run directly: python modules/places.py
    from geo import SERVICE_AREA, haversine_m

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "places.yaml")
SENSITIVE = {"school", "hospital"}
PUBLIC = {"market", "bus_stand", "railway_station", "temple", "park"}
LABELS = {"school": "school", "hospital": "hospital", "market": "market", "bus_stand": "bus stand",
          "railway_station": "railway station", "temple": "temple", "park": "park"}
NEAR_METERS = 150
_cache = {}


def load_places(path=PATH):
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)["places"]
    a = SERVICE_AREA
    for p in raw:
        for key in ("name", "type", "lat", "lon"):
            if key not in p:
                raise ValueError(f"A place is missing '{key}': {p}")
        if p["type"] not in SENSITIVE | PUBLIC:
            raise ValueError(f"{p['name']}: type must be one of {sorted(SENSITIVE | PUBLIC)}")
        if not (a["lat_min"] <= p["lat"] <= a["lat_max"] and a["lon_min"] <= p["lon"] <= a["lon_max"]):
            raise ValueError(f"{p['name']} is outside the service area")
    return raw


def all_places():
    if "places" not in _cache:
        _cache["places"] = load_places()
    return _cache["places"]


def near(lat, lon, places=None, radius_m=NEAR_METERS):
    """Places within radius_m of a point, nearest first, as {'name', 'type', 'distance_m'}."""
    found = []
    for p in (places if places is not None else all_places()):
        d = haversine_m(lat, lon, p["lat"], p["lon"])
        if d <= radius_m:
            found.append({"name": p["name"], "type": p["type"], "distance_m": d})
    return sorted(found, key=lambda x: x["distance_m"])
