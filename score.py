"""Family Fit score: percentile-rank normalization across the suburbs
within ONE metro (not across metros -- each metro's comparison set is
scored relative to itself, consistent with Premise 2: this is a
suburb-vs-suburb comparison tool, not a cross-metro one).

Percentile rank (not min-max) because min-max is outlier-fragile at the
~10-20 suburb scale a single metro has -- one suburb with an unusually bad
commute would otherwise stretch the whole 0-1 scale and compress every
other suburb's real differences on that field. Percentile rank only cares
about relative ordering, so one outlier doesn't distort everyone else's
score.

Missing-value handling (Reviewer Concern from /plan-eng-review, resolved
here): a suburb missing one score-input field is NOT zero-filled (would
unfairly penalize an otherwise-fine suburb for one unresolved fetch) and is
NOT excluded from ranking entirely (too harsh -- one missing field
shouldn't disqualify a suburb from comparison). Its Family Fit score is the
average of percentile ranks over only the fields that ARE valid for that
suburb. A suburb with fewer valid fields has a noisier score, so
`fields_scored` is included alongside the score for transparency in the
rendered output.
"""
from __future__ import annotations

from typing import Any, Optional


def score_inputs(schema: dict) -> list[tuple[str, str, str]]:
    """(category_key, field_key, score_direction) for every field flagged
    score_input: true in schema.json."""
    inputs = []
    for cat_key, cat in schema["categories"].items():
        for field_key, field in cat["fields"].items():
            if field.get("score_input"):
                inputs.append((cat_key, field_key, field["score_direction"]))
    return inputs


def _get_value(suburb_data: dict, category_key: str, field_key: str) -> Optional[float]:
    """Only a 'valid' field contributes a value -- unresolved/confirmed_absent/
    flagged fields are treated as missing for scoring purposes, same status
    discipline as everywhere else in this project."""
    field = suburb_data.get("categories", {}).get(category_key, {}).get(field_key)
    if field is None or field.get("status") != "valid":
        return None
    return field.get("value")


def _percentile_ranks(values: dict[str, float], direction: str) -> dict[str, float]:
    """Percentile rank in [0, 1] per suburb, 1.0 = best. 'neutral' direction
    fields (e.g. population, median_age -- no inherent better/worse) get a
    flat 0.5 for every suburb, so they're excluded from differentiating the
    score without needing special-case handling elsewhere."""
    if direction == "neutral":
        return {slug: 0.5 for slug in values}
    if len(values) <= 1:
        return {slug: 1.0 for slug in values}

    ordered = sorted(values.items(), key=lambda kv: kv[1])
    n = len(ordered)
    ranks: dict[str, float] = {}
    for i, (slug, _val) in enumerate(ordered):
        # i=0 is the lowest value. rank in [0,1] where 1.0 = most suburbs
        # are at or below this one -- i.e. this suburb ranks better than
        # (i / (n-1)) fraction of the others on this raw value.
        pct = i / (n - 1)
        ranks[slug] = pct if direction == "higher_better" else 1.0 - pct
    return ranks


def compute_family_fit_scores(schema: dict, suburbs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """suburbs: {slug: suburb_data} for every suburb in one metro.

    Returns {slug: {"family_fit_score": float in [0,1], "fields_scored": int,
    "fields_total": int}}.
    """
    inputs = score_inputs(schema)

    # For each score-input field, collect the raw valid values across suburbs.
    per_field_values: dict[tuple[str, str], dict[str, float]] = {}
    for category_key, field_key, _direction in inputs:
        values = {}
        for slug, data in suburbs.items():
            v = _get_value(data, category_key, field_key)
            if v is not None:
                values[slug] = v
        per_field_values[(category_key, field_key)] = values

    # Percentile-rank each field independently.
    per_field_ranks: dict[tuple[str, str], dict[str, float]] = {}
    for category_key, field_key, direction in inputs:
        values = per_field_values[(category_key, field_key)]
        per_field_ranks[(category_key, field_key)] = _percentile_ranks(values, direction)

    results: dict[str, dict[str, Any]] = {}
    for slug in suburbs:
        ranks_for_slug = [
            per_field_ranks[(cat, field)][slug]
            for cat, field, _dir in inputs
            if slug in per_field_ranks[(cat, field)]
        ]
        fields_scored = len(ranks_for_slug)
        score = sum(ranks_for_slug) / fields_scored if fields_scored > 0 else None
        results[slug] = {
            "family_fit_score": score,
            "fields_scored": fields_scored,
            "fields_total": len(inputs),
        }
    return results
