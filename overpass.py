"""OpenStreetMap Overpass API integration: amenity POI queries, batched one
call per category across a metro's whole bounding box (not per suburb) --
confirmed necessary by hitting a real 429 rate-limit on overpass-api.de
after a handful of queries during development.

Every query returns raw POIs for a category; nearest-distance-per-suburb is
computed locally (haversine) against suburb centroids, so a single category
query serves every suburb in the metro.
"""
from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Retry/backoff for the public instance's rate limiting (verified live:
# a burst of ~5 queries in quick succession returns HTTP 429).
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 10


class OverpassQueryFailed(Exception):
    """Query failed after retries -- caller should mark the field
    'unresolved', not 'confirmed_absent'."""


@dataclass
class Poi:
    name: Optional[str]
    lat: float
    lon: float


# Verified against real Boise-metro data during development:
# - retail brand regex: 3 real Target stores returned correctly
# - sport=pickleball: 183 real results (many unnamed individual court pitches)
# - leisure=sports_centre / amenity=community_centre: 129 results (includes
#   noise like small private gyms alongside actual rec centers -- same
#   low_confidence caveat schema.json already applies to this category)
# - route=mtb / mtb:scale: query executed successfully once (before being
#   rate-limited on a retry attempt) -- same query shape as the others.
CATEGORY_QUERIES: dict[str, str] = {
    "retail_target": '''
        node["shop"="department_store"]["name"~"Target",i]({bbox});
        way["shop"="department_store"]["name"~"Target",i]({bbox});
    ''',
    "retail_costco": '''
        node["shop"="wholesale"]["name"~"Costco",i]({bbox});
        way["shop"="wholesale"]["name"~"Costco",i]({bbox});
    ''',
    "retail_wholefoods": '''
        node["shop"="supermarket"]["name"~"Whole Foods|Trader Joe.?s|Sprouts",i]({bbox});
        way["shop"="supermarket"]["name"~"Whole Foods|Trader Joe.?s|Sprouts",i]({bbox});
    ''',
    "mountain_biking": '''
        way["route"="mtb"]({bbox});
        relation["route"="mtb"]({bbox});
        way["mtb:scale"]({bbox});
    ''',
    "pickleball": '''
        node["sport"="pickleball"]({bbox});
        way["sport"="pickleball"]({bbox});
    ''',
    "rec_center": '''
        node["leisure"="sports_centre"]({bbox});
        way["leisure"="sports_centre"]({bbox});
        node["amenity"="community_centre"]({bbox});
    ''',
}


def _build_query(category: str, bbox: str) -> str:
    body = CATEGORY_QUERIES[category].format(bbox=bbox)
    return f"[out:json][timeout:25];({body});out center tags;"


def fetch_category_pois(category: str, bbox: str) -> list[Poi]:
    """One batched query for a whole category across a metro's bbox
    ('south,west,north,east'). Raises OverpassQueryFailed after exhausting
    retries -- caller marks the field 'unresolved'. An empty result list
    (query succeeded, zero matches) is a valid return -- caller marks
    'confirmed_absent', not 'unresolved'."""
    query = _build_query(category, bbox)
    data = urllib.parse.urlencode({"data": query}).encode()

    last_error: Optional[Exception] = None
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(OVERPASS_URL, data=data)
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.load(resp)
            pois = []
            for el in result.get("elements", []):
                if "center" in el:
                    lat, lon = el["center"]["lat"], el["center"]["lon"]
                elif "lat" in el:
                    lat, lon = el["lat"], el["lon"]
                else:
                    continue
                pois.append(Poi(name=el.get("tags", {}).get("name"), lat=lat, lon=lon))
            return pois
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            last_error = e
            is_rate_limited = isinstance(e, urllib.error.HTTPError) and e.code in (429, 504)
            if attempt < MAX_RETRIES - 1 and is_rate_limited:
                time.sleep(BACKOFF_BASE_SECONDS * (attempt + 1))
                continue
            break

    raise OverpassQueryFailed(f"category={category!r} failed after {MAX_RETRIES} attempts: {last_error}")


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_miles = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r_miles * math.asin(math.sqrt(a))


def nearest_distance_mi(suburb_lat: float, suburb_lon: float, pois: list[Poi]) -> Optional[float]:
    """None means the category had zero POIs (confirmed_absent), not a
    fetch failure -- caller distinguishes the two by whether this function
    was reached at all (OverpassQueryFailed is raised earlier on failure)."""
    if not pois:
        return None
    return min(haversine_miles(suburb_lat, suburb_lon, p.lat, p.lon) for p in pois)


def metro_bbox(county_geometries: list[dict]) -> str:
    """Union bounding box ('south,west,north,east') across every county
    polygon in a metro -- one query per category covers the whole metro,
    not one per suburb, per the design doc's batching requirement."""
    all_lats: list[float] = []
    all_lons: list[float] = []
    for geo in county_geometries:
        for ring in geo["rings"]:
            for lon, lat in ring:
                all_lats.append(lat)
                all_lons.append(lon)
    return f"{min(all_lats)},{min(all_lons)},{max(all_lats)},{max(all_lons)}"
