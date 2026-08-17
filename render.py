"""Renders the single comparison page for a metro: suburbs as rows, fields
as columns, Family Fit score as a sortable column -- the ONLY artifact in
v1 (Premise 2), not per-suburb sub-reports.

A field with status != "valid" always renders an explicit placeholder
(never a blank cell or raw null), distinguishing three cases a suburb's
data can be in, matching the design doc's status discipline:
  - "unresolved"       -> "Not yet evaluated" (fetch failed or hasn't run)
  - "confirmed_absent"  -> "None found" (query succeeded, zero results --
                            e.g. no pickleball courts within the metro)
  - "flagged"           -> "Flagged as incorrect" (user-identified error)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _humanize_value(field_def: dict, value: Any) -> str:
    """Compact display string for one field's value. The monthly climate
    table is a 12-row structure that doesn't fit in one comparison cell --
    reduced to a compact summer-high/winter-low range instead of embedding
    all 12 rows, a decision made during render.py's build (not anticipated
    in the original schema design)."""
    if field_def["type"] == "table" and field_def.get("table_columns") == [
        "month", "avg_high_f", "avg_low_f", "avg_rainfall_in", "avg_snowfall_in"
    ]:
        if not value:
            return ""
        highs = [row["avg_high_f"] for row in value]
        lows = [row["avg_low_f"] for row in value]
        return f"Summer high ~{max(highs):.0f}°F, winter low ~{min(lows):.0f}°F"
    if field_def["type"] == "number":
        return f"{value:g}"
    return str(value)


def _sort_value(field_def: dict, value: Any) -> Optional[float]:
    if field_def["type"] == "number":
        return float(value)
    return None  # non-numeric fields sort lexicographically via cell text


def build_field_cells(schema: dict, suburb_data: dict) -> dict[str, dict[str, Any]]:
    """One cell per displayed field (every field in the schema, whether or
    not it's a score input -- score_input only controls Family Fit, not
    what's shown in the table)."""
    cells: dict[str, dict[str, Any]] = {}
    for cat_key, cat in schema["categories"].items():
        for field_key, field_def in cat["fields"].items():
            stored = suburb_data.get("categories", {}).get(cat_key, {}).get(field_key)
            if stored is None:
                cells[field_key] = {"status": "unresolved", "display_value": None, "source_url": None, "sort_value": None}
                continue
            status = stored.get("status", "unresolved")
            if status != "valid":
                cells[field_key] = {"status": status, "display_value": None, "source_url": None, "sort_value": None}
                continue
            cells[field_key] = {
                "status": "valid",
                "display_value": _humanize_value(field_def, stored["value"]),
                "source_url": stored.get("source_url"),
                "sort_value": _sort_value(field_def, stored["value"]),
            }
    return cells


def build_field_list(schema: dict) -> list[dict[str, Any]]:
    fields = []
    for cat_key, cat in schema["categories"].items():
        for field_key, field_def in cat["fields"].items():
            fields.append({
                "key": field_key,
                "label": field_def.get("description", field_key).split(" -- ")[0].split(" (")[0],
                "low_confidence": field_def.get("low_confidence", False),
                "caveat": field_def.get("caveat", ""),
            })
    return fields


def render_comparison_page(
    metro_label: str,
    schema: dict,
    suburbs_data: dict[str, dict[str, Any]],
    scores: dict[str, dict[str, Any]],
) -> str:
    fields = build_field_list(schema)
    suburbs = []
    for slug, data in sorted(suburbs_data.items(), key=lambda kv: kv[1].get("name", kv[0])):
        score_result = scores.get(slug, {"family_fit_score": None, "fields_scored": 0, "fields_total": 0})
        suburbs.append({
            "slug": slug,
            "name": data.get("name", slug),
            "score": score_result["family_fit_score"],
            "fields_scored": score_result["fields_scored"],
            "fields_total": score_result["fields_total"],
            "field_cells": build_field_cells(schema, data),
        })
    # Default sort: best Family Fit first, unscored suburbs last.
    suburbs.sort(key=lambda s: (s["score"] is None, -(s["score"] or 0)))

    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("comparison_page.html.j2")
    return template.render(metro_label=metro_label, fields=fields, suburbs=suburbs)
