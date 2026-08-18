"""Lint step: scan schema.json against every suburbs/{metro}.json and
report gaps, generalized from reloeval's lint.py to the metro/suburb
shape -- a gap is per (metro, suburb, category, field), not per city.

A "gap" is any field that needs a backfill: missing, unresolved, flagged,
confirmed_absent-but-schema-changed, or behind the schema's current
schema_version. All are backfill candidates through the same path.
confirmed_absent is deliberately NOT a gap on its own -- a query that
legitimately found nothing is not something to keep re-fetching, unlike
unresolved (Constraints: "distinct from unresolved, so the lint-driven
backfill doesn't churn forever re-querying a field that legitimately has
no OSM data").
"""
from __future__ import annotations

import sys
from pathlib import Path

from models import FieldStatus, MetroRecord, fetchable_fields, load_schema

SUBURBS_DIR = Path(__file__).parent / "suburbs"

GapReason = str  # one of: "missing", "unresolved", "flagged", "stale_version"


def find_gaps_for_suburb(schema: dict, suburb_categories: dict) -> dict[str, dict[str, GapReason]]:
    """{category_key: {field_key: reason}} for one suburb's gaps."""
    gaps: dict[str, dict[str, GapReason]] = {}
    for category_key, category in schema["categories"].items():
        field_defs = fetchable_fields(schema, category_key)
        existing_cat = suburb_categories.get(category_key, {})
        category_gaps: dict[str, GapReason] = {}
        for field_key, field_def in field_defs.items():
            current_version = field_def["schema_version"]
            existing = existing_cat.get(field_key)
            if existing is None:
                category_gaps[field_key] = "missing"
            elif existing.status == FieldStatus.UNRESOLVED:
                category_gaps[field_key] = "unresolved"
            elif existing.status == FieldStatus.FLAGGED:
                category_gaps[field_key] = "flagged"
            elif existing.status in (FieldStatus.VALID, FieldStatus.CONFIRMED_ABSENT) and existing.schema_version < current_version:
                category_gaps[field_key] = "stale_version"
        if category_gaps:
            gaps[category_key] = category_gaps
    return gaps


def list_metros() -> list[MetroRecord]:
    if not SUBURBS_DIR.exists():
        return []
    records = []
    for path in sorted(SUBURBS_DIR.glob("*.json")):
        records.append(MetroRecord.model_validate_json(path.read_text()))
    return records


def run_lint(records: list[MetroRecord]) -> dict[str, dict[str, dict[str, dict[str, GapReason]]]]:
    """{metro_slug: {suburb_slug: {category_key: {field_key: reason}}}}
    for every metro/suburb that has at least one gap."""
    schema = load_schema()
    report: dict[str, dict[str, dict[str, dict[str, GapReason]]]] = {}
    for record in records:
        metro_gaps: dict[str, dict[str, dict[str, GapReason]]] = {}
        for suburb_slug, suburb in record.suburbs.items():
            gaps = find_gaps_for_suburb(schema, suburb.categories)
            if gaps:
                metro_gaps[suburb_slug] = gaps
        if metro_gaps:
            report[record.metro_slug] = metro_gaps
    return report


def print_report(report: dict, n_metros: int) -> None:
    if n_metros == 0:
        print("No metros evaluated yet.")
        return
    if not report:
        print(f"All {n_metros} metros are fully valid and up to date. No gaps.")
        return
    for metro_slug, suburbs in report.items():
        print(f"\n{metro_slug}:")
        for suburb_slug, categories in suburbs.items():
            for category_key, fields in categories.items():
                for field_key, reason in fields.items():
                    print(f"  [{reason}] {suburb_slug}.{category_key}.{field_key}")


if __name__ == "__main__":
    records = list_metros()
    report = run_lint(records)
    print_report(report, len(records))
    sys.exit(1 if report else 0)
