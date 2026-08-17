import json
from pathlib import Path

import render

SCHEMA_PATH = Path(__file__).parent.parent / "schema.json"


def load_schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def test_valid_field_renders_value_and_citation():
    schema = load_schema()
    suburb_data = {
        "name": "Meridian",
        "categories": {
            "commute": {
                "commute_time_min": {
                    "value": 18.5, "status": "valid",
                    "source_url": "https://example.com/acs", "fetched_date": "2026-08-17",
                }
            }
        },
    }
    cells = render.build_field_cells(schema, suburb_data)
    assert cells["commute_time_min"]["status"] == "valid"
    assert cells["commute_time_min"]["display_value"] == "18.5"
    assert cells["commute_time_min"]["source_url"] == "https://example.com/acs"


def test_unresolved_field_has_no_display_value():
    schema = load_schema()
    suburb_data = {
        "name": "Nampa",
        "categories": {"commute": {"commute_time_min": {"value": None, "status": "unresolved"}}},
    }
    cells = render.build_field_cells(schema, suburb_data)
    assert cells["commute_time_min"]["status"] == "unresolved"
    assert cells["commute_time_min"]["display_value"] is None


def test_confirmed_absent_is_distinct_from_unresolved():
    schema = load_schema()
    suburb_data = {
        "name": "Star",
        "categories": {"amenities": {"pickleball_distance_mi": {"value": None, "status": "confirmed_absent"}}},
    }
    cells = render.build_field_cells(schema, suburb_data)
    assert cells["pickleball_distance_mi"]["status"] == "confirmed_absent"


def test_missing_field_entirely_defaults_to_unresolved():
    schema = load_schema()
    suburb_data = {"name": "Eagle", "categories": {}}
    cells = render.build_field_cells(schema, suburb_data)
    assert cells["commute_time_min"]["status"] == "unresolved"


def test_monthly_climate_table_compacts_to_a_range_string():
    schema = load_schema()
    table = [
        {"month": "Jan", "avg_high_f": 36.0, "avg_low_f": 24.0, "avg_rainfall_in": 1.5, "avg_snowfall_in": 5.0},
        {"month": "Jul", "avg_high_f": 92.0, "avg_low_f": 60.0, "avg_rainfall_in": 0.2, "avg_snowfall_in": 0.0},
    ]
    field_def = schema["categories"]["weather"]["fields"]["monthly_climate_table"]
    display = render._humanize_value(field_def, table)
    assert "92" in display
    assert "24" in display


def test_full_page_renders_without_error_with_mixed_statuses():
    """End-to-end: real Jinja2 render, real template file, fixture data
    covering all four status types across two suburbs."""
    schema = load_schema()
    suburbs_data = {
        "meridian-id": {
            "name": "Meridian",
            "categories": {
                "commute": {"commute_time_min": {"value": 18.0, "status": "valid", "source_url": "https://x", "fetched_date": "2026-08-17"}},
                "amenities": {"pickleball_distance_mi": {"value": None, "status": "confirmed_absent"}},
            },
        },
        "star-id": {
            "name": "Star",
            "categories": {
                "commute": {"commute_time_min": {"value": None, "status": "unresolved"}},
                "crime": {"safety_index": {"value": 85.0, "status": "flagged"}},
            },
        },
    }
    scores = {
        "meridian-id": {"family_fit_score": 0.8, "fields_scored": 5, "fields_total": 9},
        "star-id": {"family_fit_score": None, "fields_scored": 0, "fields_total": 9},
    }
    html = render.render_comparison_page("Boise, ID", schema, suburbs_data, scores)

    assert "Meridian" in html
    assert "Star" in html
    assert "Not yet evaluated" in html  # unresolved commute for Star
    assert "None found" in html  # confirmed_absent pickleball for Meridian
    assert "Flagged as incorrect" in html  # flagged safety_index for Star
    assert "No data yet" in html  # Star's None score


def test_suburbs_sorted_by_score_descending():
    schema = load_schema()
    suburbs_data = {
        "low-id": {"name": "Low Score", "categories": {}},
        "high-id": {"name": "High Score", "categories": {}},
    }
    scores = {
        "low-id": {"family_fit_score": 0.2, "fields_scored": 3, "fields_total": 9},
        "high-id": {"family_fit_score": 0.9, "fields_scored": 3, "fields_total": 9},
    }
    html = render.render_comparison_page("Boise, ID", schema, suburbs_data, scores)
    assert html.index("High Score") < html.index("Low Score")
