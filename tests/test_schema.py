import json
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent.parent / "schema.json"


def load_schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def all_fields():
    schema = load_schema()
    for cat_key, cat in schema["categories"].items():
        for field_key, field in cat["fields"].items():
            yield cat_key, field_key, field


def test_schema_is_valid_json():
    load_schema()  # no raise


def test_every_field_has_required_base_keys():
    for cat_key, field_key, field in all_fields():
        for required in ("type", "source", "requires_citation", "low_confidence", "schema_version"):
            assert required in field, f"{cat_key}.{field_key} missing {required!r}"


def test_every_field_has_source_api_or_llm():
    for cat_key, field_key, field in all_fields():
        assert field["source"] in ("api", "llm"), f"{cat_key}.{field_key} has bad source {field['source']!r}"


def test_every_api_field_declares_api_source():
    for cat_key, field_key, field in all_fields():
        if field["source"] == "api":
            assert "api_source" in field, f"{cat_key}.{field_key} is source=api but missing api_source"
            assert field["api_source"] in ("census_acs", "census_bps", "overpass"), (
                f"{cat_key}.{field_key} has unknown api_source {field.get('api_source')!r}"
            )


def test_every_score_input_field_has_a_direction():
    """Every field that feeds the Family Fit score must declare which
    direction is 'better' -- this is the per-field direction table the
    design doc's Constraints section requires before score.py can be
    written (score_direction: higher_better | lower_better | neutral)."""
    for cat_key, field_key, field in all_fields():
        if field.get("score_input"):
            assert "score_direction" in field, f"{cat_key}.{field_key} is score_input but has no score_direction"
            assert field["score_direction"] in ("higher_better", "lower_better", "neutral"), (
                f"{cat_key}.{field_key} has bad score_direction {field.get('score_direction')!r}"
            )


def test_low_confidence_fields_have_a_caveat():
    for cat_key, field_key, field in all_fields():
        if field.get("low_confidence"):
            assert field.get("caveat"), f"{cat_key}.{field_key} is low_confidence but has no caveat text"


def test_self_sufficiency_fields_are_display_only():
    """Locks the design decision: self-sufficiency is folded into the table
    but excluded from the Family Fit score."""
    schema = load_schema()
    for field_key, field in schema["categories"]["self_sufficiency"]["fields"].items():
        assert field["score_input"] is False, f"self_sufficiency.{field_key} must not be a score input"


def test_weather_is_display_only():
    schema = load_schema()
    field = schema["categories"]["weather"]["fields"]["monthly_climate_table"]
    assert field["score_input"] is False
