"""metros.json loading and validation.

metros.json is hand-edited (a new metro is added by typing an entry), so a
malformed entry must fail loudly at pipeline start -- pointing at the file --
rather than surfacing as a confusing downstream Census API error partway
through a run.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

METROS_PATH = Path(__file__).parent / "metros.json"

_STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
_STATE_FIPS_RE = re.compile(r"^\d{2}$")
_COUNTY_FIPS_RE = re.compile(r"^\d{3}$")


class MetroConfigError(ValueError):
    """A metros.json entry is malformed. Raised before any fetch runs."""


def load_metros() -> dict[str, dict[str, Any]]:
    with open(METROS_PATH) as f:
        metros = json.load(f)
    for slug, entry in metros.items():
        validate_metro_entry(slug, entry)
    return metros


def validate_metro_entry(slug: str, entry: dict[str, Any]) -> None:
    if not isinstance(entry.get("label"), str) or not entry["label"].strip():
        raise MetroConfigError(f"metros.json[{slug!r}]: missing or empty 'label'")

    state = entry.get("state")
    if not isinstance(state, str) or not _STATE_CODE_RE.match(state):
        raise MetroConfigError(
            f"metros.json[{slug!r}]: 'state' must be a 2-letter uppercase code, got {state!r}"
        )

    state_fips = entry.get("state_fips")
    if not isinstance(state_fips, str) or not _STATE_FIPS_RE.match(state_fips):
        raise MetroConfigError(
            f"metros.json[{slug!r}]: 'state_fips' must be a 2-digit string, got {state_fips!r}"
        )

    counties = entry.get("counties")
    if not isinstance(counties, list) or len(counties) == 0:
        raise MetroConfigError(
            f"metros.json[{slug!r}]: 'counties' must be a non-empty list"
        )
    for county in counties:
        if not isinstance(county, dict):
            raise MetroConfigError(f"metros.json[{slug!r}]: each county must be an object")
        name = county.get("name")
        fips = county.get("fips")
        if not isinstance(name, str) or not name.strip():
            raise MetroConfigError(f"metros.json[{slug!r}]: county missing 'name'")
        if not isinstance(fips, str) or not _COUNTY_FIPS_RE.match(fips):
            raise MetroConfigError(
                f"metros.json[{slug!r}]: county {name!r} 'fips' must be a 3-digit string, got {fips!r}"
            )


def slugify_metro(label: str) -> str:
    """'Boise, ID' -> 'boise-id'. Same convention as reloeval's city slugs."""
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
