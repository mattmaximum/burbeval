import json
from pathlib import Path

import score

SCHEMA_PATH = Path(__file__).parent.parent / "schema.json"


def load_schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def valid_field(value):
    return {"value": value, "status": "valid", "source_url": "http://example.com", "fetched_date": "2026-08-17", "schema_version": 1}


def unresolved_field():
    return {"value": None, "status": "unresolved", "source_url": None, "fetched_date": None, "schema_version": 1}


def test_lower_better_field_ranks_smallest_value_highest():
    values = {"a": 30.0, "b": 10.0, "c": 20.0}
    ranks = score._percentile_ranks(values, "lower_better")
    assert ranks["b"] > ranks["c"] > ranks["a"]
    assert ranks["b"] == 1.0
    assert ranks["a"] == 0.0


def test_higher_better_field_ranks_largest_value_highest():
    values = {"a": 30.0, "b": 10.0, "c": 20.0}
    ranks = score._percentile_ranks(values, "higher_better")
    assert ranks["a"] > ranks["c"] > ranks["b"]
    assert ranks["a"] == 1.0
    assert ranks["b"] == 0.0


def test_neutral_field_gives_flat_half_to_everyone():
    values = {"a": 999.0, "b": 1.0}
    ranks = score._percentile_ranks(values, "neutral")
    assert ranks == {"a": 0.5, "b": 0.5}


def test_single_suburb_gets_perfect_rank():
    ranks = score._percentile_ranks({"a": 42.0}, "lower_better")
    assert ranks == {"a": 1.0}


def test_outlier_does_not_distort_the_rest_of_the_scale():
    """The whole point of switching from min-max to percentile-rank: one
    extreme outlier must not compress everyone else's relative ordering."""
    values = {"a": 10.0, "b": 12.0, "c": 14.0, "outlier": 500.0}
    ranks = score._percentile_ranks(values, "lower_better")
    # a, b, c should still be cleanly separated near the top of the scale,
    # not all crushed toward 0 by the outlier the way min-max would (with
    # min-max, 10/12/14 would all land within ~1% of each other since 500
    # dominates the range; percentile rank spaces them evenly instead).
    assert ranks["a"] - ranks["b"] == pytest_approx(1 / 3)
    assert ranks["b"] - ranks["c"] == pytest_approx(1 / 3)
    assert ranks["outlier"] == 0.0


def pytest_approx(x, tol=1e-9):
    class _Approx(float):
        def __eq__(self, other):
            return abs(other - x) < tol
    return _Approx(x)


def test_compute_family_fit_scores_end_to_end_with_missing_field():
    schema = load_schema()
    suburbs = {
        "meridian-id": {
            "categories": {
                "commute": {"commute_time_min": valid_field(18.0)},
                "crime": {
                    "violent_crime_rate": valid_field(2.0),
                    "property_crime_rate": valid_field(15.0),
                    "safety_index": valid_field(80.0),
                },
            }
        },
        "nampa-id": {
            "categories": {
                "commute": {"commute_time_min": valid_field(25.0)},
                "crime": {
                    "violent_crime_rate": unresolved_field(),  # missing on purpose
                    "property_crime_rate": valid_field(18.0),
                    "safety_index": valid_field(70.0),
                },
            }
        },
    }
    results = score.compute_family_fit_scores(schema, suburbs)

    assert results["meridian-id"]["family_fit_score"] > results["nampa-id"]["family_fit_score"]
    # nampa is missing one field it has data for (violent_crime_rate) among
    # the fields BOTH suburbs have any data for -- fields_scored reflects that.
    assert results["nampa-id"]["fields_scored"] < results["meridian-id"]["fields_scored"]
    assert results["meridian-id"]["fields_scored"] <= results["meridian-id"]["fields_total"]


def test_suburb_with_zero_valid_fields_gets_none_score():
    schema = load_schema()
    suburbs = {
        "empty-id": {"categories": {}},
    }
    results = score.compute_family_fit_scores(schema, suburbs)
    assert results["empty-id"]["family_fit_score"] is None
    assert results["empty-id"]["fields_scored"] == 0
