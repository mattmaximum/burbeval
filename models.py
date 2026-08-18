"""Pydantic models mirroring schema.json, same pattern as reloeval's
models.py: built dynamically from schema.json so the two never drift.
"""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Type

from pydantic import BaseModel, Field, create_model

SCHEMA_PATH = Path(__file__).parent / "schema.json"


class FieldStatus(str, Enum):
    VALID = "valid"
    UNRESOLVED = "unresolved"
    CONFIRMED_ABSENT = "confirmed_absent"
    FLAGGED = "flagged"


class ClimateMonthRow(BaseModel):
    month: str
    avg_high_f: float
    avg_low_f: float
    avg_rainfall_in: float
    avg_snowfall_in: float


_TYPE_MAP: dict[str, Any] = {
    "string": str,
    "number": float,
    "table": list[ClimateMonthRow],
}


class StoredFieldValue(BaseModel):
    value: Optional[Any] = None
    source_url: Optional[str] = None
    fetched_date: Optional[str] = None
    status: FieldStatus
    schema_version: int


def load_schema() -> dict:
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def llm_fields(schema: dict, category_key: str) -> dict[str, dict]:
    """Fields in a category sourced from the LLM (source: 'llm') -- the
    only fields sent to the LLM structured-output fetch call. API-sourced
    fields in the same category (e.g. schools.school_locations, source:
    'api') are filled by census.py/overpass.py separately, not here."""
    fields = schema["categories"][category_key]["fields"]
    return {k: v for k, v in fields.items() if v.get("source") == "llm"}


def api_fields(schema: dict, category_key: str) -> dict[str, dict]:
    fields = schema["categories"][category_key]["fields"]
    return {k: v for k, v in fields.items() if v.get("source") == "api"}


def build_field_value_model(field_def: dict, enforce_bounds: bool = True) -> Type[BaseModel]:
    """The {value, source_url, fetched_date} shape the LLM must return for
    one field. enforce_bounds=False is used for the outgoing request schema
    (min/max on a JSON-schema request 400s on some providers, same
    residual issue reloeval's models.py documents) -- True for validating
    the response after it comes back."""
    value_type = _TYPE_MAP[field_def["type"]]
    if enforce_bounds and ("min" in field_def or "max" in field_def):
        value_spec = (value_type, Field(..., ge=field_def.get("min"), le=field_def.get("max")))
    else:
        value_spec = (value_type, ...)
    return create_model(
        "FetchedFieldValue",
        value=value_spec,
        source_url=(str, ...),
        fetched_date=(str, ...),
    )


def build_category_response_model(schema: dict, category_key: str) -> Type[BaseModel]:
    fields = llm_fields(schema, category_key)
    field_defs = {
        key: (build_field_value_model(field_def, enforce_bounds=False), ...)
        for key, field_def in fields.items()
    }
    return create_model(f"{category_key}_response", **field_defs)
