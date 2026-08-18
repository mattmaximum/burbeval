import json

import pytest

import evaluate
from models import FieldStatus, MetroRecord


FAKE_SUBURBS = [
    {"name": "Meridian city", "geoid": "1650770", "place_fips": "50770", "kind": "incorporated", "lat": 43.6121, "lon": -116.3915},
    {"name": "Star city", "geoid": "1676260", "place_fips": "76260", "kind": "incorporated", "lat": 43.6866, "lon": -116.4930},
]


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate, "SUBURBS_DIR", tmp_path / "suburbs")
    monkeypatch.setattr(evaluate, "SITE_DIR", tmp_path / "_site")
    return tmp_path


@pytest.mark.asyncio
async def test_evaluate_metro_unknown_slug_raises(isolated_dirs):
    with pytest.raises(evaluate.MetroNotFoundError):
        await evaluate.evaluate_metro("nowhere-xx")


@pytest.mark.asyncio
async def test_evaluate_metro_end_to_end_with_mocked_apis(isolated_dirs, monkeypatch):
    monkeypatch.setattr(evaluate, "enumerate_suburbs", lambda state_fips, counties: FAKE_SUBURBS)
    monkeypatch.setattr(evaluate, "fetch_county_geometry", lambda state_fips, county_fips: {
        "attributes": {}, "geometry": {"rings": [[[-116.6, 43.5], [-116.2, 43.5], [-116.2, 43.8], [-116.6, 43.8]]]},
        "spatialReference": {"wkid": 4326},
    })

    def fake_acs_batch(state_fips, place_fips_list, variables):
        return {
            "50770": {"B01003_001E": "117635", "B01002_001E": "35.2", "B19013_001E": "95000"},
            "76260": {"B01003_001E": "10500", "B01002_001E": "38.0", "B19013_001E": "88000"},
        }
    monkeypatch.setattr(evaluate, "fetch_acs_batch", fake_acs_batch)

    def fake_fetch_pois(category, bbox):
        if category == "pickleball":
            return []  # confirmed_absent for every suburb
        return [type("Poi", (), {"name": "Target", "lat": 43.62, "lon": -116.39})()]
    monkeypatch.setattr(evaluate, "fetch_category_pois", fake_fetch_pois)

    async def fake_llm_fetch(schema, suburb_names, metro_label):
        return {
            name: {
                "crime": {
                    "violent_crime_rate": {"value": 2.0, "status": "valid", "source_url": "https://x", "fetched_date": "2026-08-17", "schema_version": 1},
                    "property_crime_rate": {"value": 15.0, "status": "valid", "source_url": "https://x", "fetched_date": "2026-08-17", "schema_version": 1},
                    "safety_index": {"value": 80.0, "status": "valid", "source_url": "https://x", "fetched_date": "2026-08-17", "schema_version": 1},
                }
            }
            for name in suburb_names
        }
    monkeypatch.setattr(evaluate, "fetch_llm_fields_for_metro", fake_llm_fetch)

    slug = await evaluate.evaluate_metro("boise-id")
    assert slug == "boise-id"

    suburbs_file = isolated_dirs / "suburbs" / "boise-id.json"
    site_file = isolated_dirs / "_site" / "boise-id.html"
    assert suburbs_file.exists()
    assert site_file.exists()

    record = MetroRecord.model_validate_json(suburbs_file.read_text())
    assert set(record.suburbs.keys()) == {"meridian-city", "star-city"}

    meridian = record.suburbs["meridian-city"]
    assert meridian.categories["population_growth"]["population"].status == FieldStatus.VALID
    assert meridian.categories["population_growth"]["population"].value == 117635.0
    # growth_rate is intentionally not wired yet (BPS still an open question).
    assert meridian.categories["population_growth"]["growth_rate"].status == FieldStatus.UNRESOLVED
    # commute_time_min is intentionally excluded (wrong ACS variable caught during build).
    assert meridian.categories["commute"]["commute_time_min"].status == FieldStatus.UNRESOLVED
    # pickleball returned zero POIs -> confirmed_absent, not unresolved.
    assert meridian.categories["amenities"]["pickleball_distance_mi"].status == FieldStatus.CONFIRMED_ABSENT
    assert meridian.categories["amenities"]["retail_target_distance_mi"].status == FieldStatus.VALID
    assert meridian.categories["crime"]["safety_index"].value == 80.0

    html = site_file.read_text()
    assert "Meridian" in html
    assert "Star" in html
