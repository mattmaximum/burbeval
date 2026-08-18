import json
from pathlib import Path

from lint import find_gaps_for_suburb, run_lint
from models import FieldStatus, MetroRecord, StoredFieldValue

SCHEMA_PATH = Path(__file__).parent.parent / "schema.json"


def load_schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def test_missing_field_is_a_gap():
    schema = load_schema()
    gaps = find_gaps_for_suburb(schema, {})
    assert "commute" in gaps
    assert gaps["commute"]["commute_time_min"] == "missing"


def test_unresolved_field_is_a_gap():
    schema = load_schema()
    categories = {"commute": {"commute_time_min": StoredFieldValue(status=FieldStatus.UNRESOLVED, schema_version=1)}}
    gaps = find_gaps_for_suburb(schema, categories)
    assert gaps["commute"]["commute_time_min"] == "unresolved"


def test_confirmed_absent_is_not_a_gap():
    """The whole point of the confirmed_absent status: a legitimately-empty
    query result should not be treated as needing a backfill."""
    schema = load_schema()
    categories = {
        "amenities": {
            "pickleball_distance_mi": StoredFieldValue(status=FieldStatus.CONFIRMED_ABSENT, schema_version=1)
        }
    }
    gaps = find_gaps_for_suburb(schema, categories)
    assert "amenities" not in gaps or "pickleball_distance_mi" not in gaps.get("amenities", {})


def test_flagged_field_is_a_gap():
    schema = load_schema()
    categories = {"crime": {"safety_index": StoredFieldValue(status=FieldStatus.FLAGGED, schema_version=1)}}
    gaps = find_gaps_for_suburb(schema, categories)
    assert gaps["crime"]["safety_index"] == "flagged"


def test_stale_schema_version_is_a_gap():
    schema = load_schema()
    categories = {
        "commute": {
            "commute_time_min": StoredFieldValue(value=18.0, status=FieldStatus.VALID, schema_version=0)
        }
    }
    gaps = find_gaps_for_suburb(schema, categories)
    assert gaps["commute"]["commute_time_min"] == "stale_version"


def test_valid_current_field_is_not_a_gap():
    schema = load_schema()
    categories = {
        "commute": {
            "commute_time_min": StoredFieldValue(value=18.0, status=FieldStatus.VALID, schema_version=1)
        }
    }
    gaps = find_gaps_for_suburb(schema, categories)
    assert "commute" not in gaps


def test_run_lint_skips_metros_with_no_gaps():
    metro = MetroRecord(
        metro_slug="boise-id",
        metro_label="Boise, ID",
        suburbs={
            "meridian-id": {"name": "Meridian", "categories": {}},
        },
    )
    report = run_lint([metro])
    # meridian-id has zero fields fetched at all -> every field is "missing" -> a real gap.
    assert "boise-id" in report
    assert "meridian-id" in report["boise-id"]


def test_adding_a_field_to_schema_surfaces_as_a_gap_for_existing_suburbs():
    """Simulates the 'update all files easily' scenario: a suburb has
    every CURRENT field valid, but the schema gains a new field the suburb
    has never seen -- lint must surface it as missing."""
    schema = load_schema()
    full_categories = {}
    for cat_key, cat in schema["categories"].items():
        full_categories[cat_key] = {}
        for field_key, field_def in cat["fields"].items():
            full_categories[cat_key][field_key] = StoredFieldValue(
                value=1.0 if field_def["type"] == "number" else "x",
                status=FieldStatus.VALID,
                schema_version=field_def["schema_version"],
            )
    gaps_before = find_gaps_for_suburb(schema, full_categories)
    assert gaps_before == {}

    schema["categories"]["commute"]["fields"]["brand_new_field"] = {
        "type": "string", "source": "llm", "requires_citation": True, "low_confidence": False, "schema_version": 1,
    }
    gaps_after = find_gaps_for_suburb(schema, full_categories)
    assert gaps_after["commute"]["brand_new_field"] == "missing"
