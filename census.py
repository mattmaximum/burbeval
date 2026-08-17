"""Census Bureau integration: suburb enumeration (TIGERweb, no API key) and
batched demographic/growth fetch (ACS + Building Permits Survey, needs
CENSUS_API_KEY -- free at https://api.census.gov/data/key_signup.html).

Suburb enumeration deliberately does NOT filter Places by a COUNTY attribute
-- TIGERweb's Incorporated Places / CDP layers don't carry one, because a
place can span multiple counties (verified against real data: Meridian,
Nampa, and Star all intersect both Ada and Canyon County in Idaho). Instead
this fetches the county's polygon and spatially queries places that
intersect it -- a place split across the metro's county boundary is
included, not silently dropped.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

TIGERWEB_BASE = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/MapServer"
COUNTIES_LAYER = 82
INCORPORATED_PLACES_LAYER = 28
CDP_LAYER = 30

ACS_BASE = "https://api.census.gov/data/2023/acs/acs5"
# NOTE: exact vintage/dataset for building-permit data is an open question
# (see design doc "Open Questions" -- BPS granularity for a given metro
# settles during build against real data).


def _arcgis_query(layer_id: int, params: dict[str, str]) -> dict[str, Any]:
    url = f"{TIGERWEB_BASE}/{layer_id}/query"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.load(resp)
    if "error" in result:
        raise RuntimeError(f"TIGERweb query failed (layer {layer_id}): {result['error']}")
    return result


def fetch_county_geometry(state_fips: str, county_fips: str) -> dict[str, Any]:
    """Returns {'attributes': {...}, 'geometry': {...}, 'spatialReference': {...}}
    for one county, or raises if the county isn't found."""
    result = _arcgis_query(
        COUNTIES_LAYER,
        {
            "where": f"STATE='{state_fips}' AND COUNTY='{county_fips}'",
            "outFields": "NAME,STATE,COUNTY,GEOID",
            "returnGeometry": "true",
            "geometryPrecision": "4",
            "f": "json",
        },
    )
    features = result.get("features", [])
    if not features:
        raise RuntimeError(f"No county found for state={state_fips} county={county_fips}")
    feature = features[0]
    return {
        "attributes": feature["attributes"],
        "geometry": feature["geometry"],
        "spatialReference": result["spatialReference"],
    }


def _places_intersecting(geometry: dict, spatial_ref: dict, layer_id: int) -> list[dict[str, Any]]:
    geometry_param = json.dumps({"rings": geometry["rings"], "spatialReference": spatial_ref})
    result = _arcgis_query(
        layer_id,
        {
            "geometry": geometry_param,
            "geometryType": "esriGeometryPolygon",
            "spatialRel": "esriSpatialRelIntersects",
            "inSR": json.dumps(spatial_ref),
            "outFields": "NAME,STATE,PLACE,GEOID,FUNCSTAT",
            "returnGeometry": "false",
            "f": "json",
        },
    )
    return [f["attributes"] for f in result.get("features", [])]


def enumerate_suburbs(state_fips: str, counties: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Returns deduplicated incorporated places + CDPs across every county in
    the metro. A place intersecting more than one of the metro's own counties
    (e.g. Meridian spanning Ada and Canyon) appears once, not once per county.

    Each entry: {"name": str, "geoid": str, "place_fips": str, "kind": "incorporated"|"cdp"}
    """
    by_geoid: dict[str, dict[str, Any]] = {}
    for county in counties:
        county_geo = fetch_county_geometry(state_fips, county["fips"])
        geometry = county_geo["geometry"]
        spatial_ref = county_geo["spatialReference"]

        for attrs in _places_intersecting(geometry, spatial_ref, INCORPORATED_PLACES_LAYER):
            by_geoid[attrs["GEOID"]] = {
                "name": attrs["NAME"],
                "geoid": attrs["GEOID"],
                "place_fips": attrs["PLACE"],
                "kind": "incorporated",
            }
        for attrs in _places_intersecting(geometry, spatial_ref, CDP_LAYER):
            by_geoid[attrs["GEOID"]] = {
                "name": attrs["NAME"],
                "geoid": attrs["GEOID"],
                "place_fips": attrs["PLACE"],
                "kind": "cdp",
            }

    return sorted(by_geoid.values(), key=lambda p: p["name"])


def fetch_acs_batch(state_fips: str, place_fips_list: list[str], variables: list[str]) -> dict[str, dict[str, str]]:
    """One ACS API call covering every suburb's place FIPS at once (comma-
    separated place codes), not one call per suburb -- see design doc
    Performance section. Requires CENSUS_API_KEY.

    Returns {place_fips: {variable: value}}.
    """
    api_key = os.environ.get("CENSUS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "CENSUS_API_KEY not set. Get a free key at "
            "https://api.census.gov/data/key_signup.html and export it, "
            "or add it as a GitHub Actions secret for the deployed pipeline."
        )
    places_param = ",".join(place_fips_list)
    get_param = ",".join(["NAME", *variables])
    url = (
        f"{ACS_BASE}?get={urllib.parse.quote(get_param)}"
        f"&for=place:{places_param}&in=state:{state_fips}&key={api_key}"
    )
    with urllib.request.urlopen(url, timeout=30) as resp:
        rows = json.load(resp)

    header, *data_rows = rows
    place_col = header.index("place")
    results: dict[str, dict[str, str]] = {}
    for row in data_rows:
        place_fips = row[place_col]
        results[place_fips] = dict(zip(header, row))
    return results
