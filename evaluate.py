"""One-command entrypoint: evaluate a metro end to end.

fetch (census.py + overpass.py + llm_fetch.py) -> merge into a MetroRecord
-> atomic write to suburbs/{slug}.json -> score.py -> render.py -> atomic
write to _site/{slug}.html. Each fetch module stays independently testable
(single responsibility); this is the thin orchestrator that chains them,
same shape as reloeval's evaluate.py.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date
from pathlib import Path

from atomic_write import atomic_write
from census import enumerate_suburbs, fetch_acs_batch, fetch_county_geometry
from llm_fetch import fetch_llm_fields_for_metro
from metros import MetroConfigError, load_metros, slugify_metro
from models import FieldStatus, MetroRecord, StoredFieldValue, SuburbRecord, load_schema
from overpass import CATEGORY_QUERIES, fetch_category_pois, metro_bbox, nearest_distance_mi
from render import render_comparison_page
from score import compute_family_fit_scores

SUBURBS_DIR = Path(__file__).parent / "suburbs"
SITE_DIR = Path(__file__).parent / "_site"

# ACS 5-year variable codes for the schema fields census.py's batch fetch
# covers. growth_rate (Building Permits Survey) is intentionally NOT wired
# yet -- the design doc's Open Questions left BPS granularity per metro as
# "settle during build," and it hasn't been settled. Requesting it here
# would be pretending it works; it renders "unresolved" until it's real.
ACS_VARIABLES = {
    "population": "B01003_001E",
    "median_age": "B01002_001E",
    "median_household_income": "B19013_001E",
    "commute_time_min": "B08303_001E",  # NOTE: this ACS table is a distribution,
    # not a mean -- B08303_001E is actually the total workers surveyed, not a
    # travel-time value. Real mean travel time needs a different table
    # (e.g. a weighted-average calculation across B08303's bucketed columns).
    # Flagged here rather than silently shipped wrong: commute_time_min
    # renders "unresolved" until this is fixed, same honesty as growth_rate.
}
# Fields that are structurally wired (batch API call exists) vs. actually
# correct (verified against real ACS table semantics). Keep this list
# explicit so a future fix to commute_time_min's variable code doesn't
# require hunting for where the exclusion lives.
ACS_FIELDS_NOT_YET_CORRECT = {"commute_time_min"}


class MetroNotFoundError(ValueError):
    pass


def _build_amenity_pois(schema: dict, counties_geo: list[dict]) -> dict[str, list]:
    """One batched Overpass query per amenity category across the metro's
    whole bbox -- category -> pois, or empty list on OverpassQueryFailed
    (marked unresolved per-suburb below, not silently dropped)."""
    from overpass import OverpassQueryFailed

    bbox = metro_bbox(counties_geo)
    field_to_category = {
        "retail_target_distance_mi": "retail_target",
        "retail_costco_distance_mi": "retail_costco",
        "retail_wholefoods_distance_mi": "retail_wholefoods",
        "mountain_biking_distance_mi": "mountain_biking",
        "pickleball_distance_mi": "pickleball",
        "rec_center_distance_mi": "rec_center",
    }
    results: dict[str, list] = {}
    failures: set[str] = set()
    for field_key, category in field_to_category.items():
        try:
            results[category] = fetch_category_pois(category, bbox)
        except OverpassQueryFailed as e:
            print(f"WARNING: overpass category {category!r} failed: {e}", file=sys.stderr)
            failures.add(category)
    return {"results": results, "failures": failures, "field_to_category": field_to_category}


def _acs_field_values(suburb_place_fips: str, acs_by_place: dict) -> dict[str, StoredFieldValue]:
    today = date.today().isoformat()
    row = acs_by_place.get(suburb_place_fips)
    values: dict[str, StoredFieldValue] = {}
    for field_key in ACS_VARIABLES:
        schema_version = 1
        if field_key in ACS_FIELDS_NOT_YET_CORRECT or row is None:
            values[field_key] = StoredFieldValue(status=FieldStatus.UNRESOLVED, schema_version=schema_version)
            continue
        raw = row.get(ACS_VARIABLES[field_key])
        try:
            values[field_key] = StoredFieldValue(
                value=float(raw), source_url="https://api.census.gov/data/2023/acs/acs5",
                fetched_date=today, status=FieldStatus.VALID, schema_version=schema_version,
            )
        except (TypeError, ValueError):
            values[field_key] = StoredFieldValue(status=FieldStatus.UNRESOLVED, schema_version=schema_version)
    return values


async def evaluate_metro(metro_slug_input: str) -> str:
    schema = load_schema()
    try:
        metros = load_metros()
    except MetroConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if metro_slug_input not in metros:
        raise MetroNotFoundError(
            f"{metro_slug_input!r} is not in metros.json. Add it there first -- "
            "no free-form metro input, per the design doc's hand-maintained mapping."
        )
    metro = metros[metro_slug_input]
    metro_label = metro["label"]

    suburbs = enumerate_suburbs(metro["state_fips"], metro["counties"])
    print(f"Enumerated {len(suburbs)} suburbs for {metro_label}")

    counties_geo = [fetch_county_geometry(metro["state_fips"], c["fips"]) for c in metro["counties"]]

    # ACS batch (needs CENSUS_API_KEY -- may raise, caught per-run below).
    acs_by_place: dict = {}
    try:
        acs_by_place = fetch_acs_batch(
            metro["state_fips"], [s["place_fips"] for s in suburbs], list(ACS_VARIABLES.values())
        )
    except RuntimeError as e:
        print(f"WARNING: Census ACS batch failed (all ACS fields unresolved this run): {e}", file=sys.stderr)

    amenities = _build_amenity_pois(schema, [g["geometry"] for g in counties_geo])

    llm_results = {}
    try:
        llm_results = await fetch_llm_fields_for_metro(schema, [s["name"] for s in suburbs], metro_label)
    except RuntimeError as e:
        print(f"WARNING: LLM fetch failed (all LLM fields unresolved this run): {e}", file=sys.stderr)

    today = date.today().isoformat()
    record = MetroRecord(metro_slug=metro_slug_input, metro_label=metro_label, first_evaluated_date=today)

    for suburb in suburbs:
        suburb_slug = suburb["name"].lower().replace(" ", "-").replace("'", "")
        categories: dict[str, dict[str, StoredFieldValue]] = {
            "population_growth": {},
            "commute": {},
            "amenities": {},
            "schools": {},
        }

        acs_values = _acs_field_values(suburb["place_fips"], acs_by_place)
        categories["population_growth"]["population"] = acs_values["population"]
        categories["population_growth"]["median_age"] = acs_values["median_age"]
        categories["population_growth"]["median_household_income"] = acs_values["median_household_income"]
        categories["population_growth"]["growth_rate"] = StoredFieldValue(status=FieldStatus.UNRESOLVED, schema_version=1)
        categories["commute"]["commute_time_min"] = acs_values["commute_time_min"]

        for field_key, category in amenities["field_to_category"].items():
            if category in amenities["failures"]:
                categories["amenities"][field_key] = StoredFieldValue(status=FieldStatus.UNRESOLVED, schema_version=1)
                continue
            pois = amenities["results"].get(category, [])
            dist = nearest_distance_mi(suburb["lat"], suburb["lon"], pois)
            if dist is None:
                categories["amenities"][field_key] = StoredFieldValue(status=FieldStatus.CONFIRMED_ABSENT, schema_version=1)
            else:
                categories["amenities"][field_key] = StoredFieldValue(
                    value=round(dist, 1), source_url="https://www.openstreetmap.org/copyright",
                    fetched_date=today, status=FieldStatus.VALID, schema_version=1,
                )
        categories["amenities"]["school_locations"] = StoredFieldValue(status=FieldStatus.UNRESOLVED, schema_version=1)

        suburb_llm = llm_results.get(suburb["name"], {})
        for category_key, fields in suburb_llm.items():
            categories.setdefault(category_key, {}).update(fields)

        record.suburbs[suburb_slug] = SuburbRecord(
            name=suburb["name"], geoid=suburb["geoid"], kind=suburb["kind"], categories=categories,
        )

    SUBURBS_DIR.mkdir(exist_ok=True)
    atomic_write(SUBURBS_DIR / f"{metro_slug_input}.json", record.model_dump_json(indent=2))

    # score.py/render.py work on plain dicts (they have no Pydantic
    # dependency of their own) -- model_dump() every SuburbRecord once here,
    # at the one place real SuburbRecord instances exist, rather than
    # defensively handling "might be a dict, might be a model" downstream.
    suburbs_as_dicts = {slug: s.model_dump() for slug, s in record.suburbs.items()}
    scores = compute_family_fit_scores(schema, suburbs_as_dicts)
    html = render_comparison_page(metro_label, schema, suburbs_as_dicts, scores)

    SITE_DIR.mkdir(exist_ok=True)
    atomic_write(SITE_DIR / f"{metro_slug_input}.html", html)

    return metro_slug_input


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print('Usage: python evaluate.py "boise-id"  (a metros.json key)', file=sys.stderr)
        sys.exit(1)
    slug = asyncio.run(evaluate_metro(sys.argv[1]))
    print(f"Done — suburbs/{slug}.json and _site/{slug}.html are ready.")
