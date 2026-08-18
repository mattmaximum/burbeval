"""LLM-sourced field fetch: crime, school ratings, weather, self-sufficiency
-- the fields with no clean public API. Structured output via OpenRouter's
OpenAI-compatible endpoint, same pattern as reloeval's fetch.py.

Model tiering matches reloeval exactly: CATEGORY_MODEL (cheap) for every
per-suburb category call, MODEL (pricier) reserved for nothing here since
there's no per-run normalization call in this pipeline (see design doc's
Constraints) -- but the split is kept structurally identical to reloeval's
so it's a one-line change if a normalization call is ever added. This
matters more here than in reloeval: reloeval fans out 1 city x 7
categories per run, this tool fans out N suburbs (20-30) x LLM categories
per run.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date
from typing import Optional

from openai import AsyncOpenAI
from pydantic import ValidationError

from models import (
    FieldStatus,
    StoredFieldValue,
    build_category_response_model,
    build_field_value_model,
    llm_fields,
)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
CATEGORY_MODEL = "anthropic/claude-haiku-4.5"
WEB_PLUGIN_MAX_RESULTS = 10

LLM_CATEGORIES = ["crime", "weather", "schools", "self_sufficiency"]


async def fetch_llm_category(
    client: AsyncOpenAI,
    schema: dict,
    category_key: str,
    suburb_name: str,
    metro_label: str,
) -> dict[str, StoredFieldValue]:
    """Fetch every LLM-sourced field in one category for one suburb.
    Never raises -- a total category failure falls through to marking
    every field in the category unresolved, same as a single bad field.
    Retries once, matching reloeval's fetch_category (concurrent-load
    transient errors observed to succeed on a bare retry)."""
    field_defs = llm_fields(schema, category_key)
    if not field_defs:
        return {}
    category_label = schema["categories"][category_key]["label"]
    response_model = build_category_response_model(schema, category_key)

    location = f"{suburb_name}, part of the {metro_label} metro area"

    raw: dict = {}
    last_error: Optional[Exception] = None
    for attempt in range(2):
        try:
            response = await client.chat.completions.create(
                model=CATEGORY_MODEL,
                max_tokens=4096,
                extra_body={"plugins": [{"id": "web", "max_results": WEB_PLUGIN_MAX_RESULTS}]},
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "category_data", "schema": response_model.model_json_schema()},
                },
                messages=[{
                    "role": "user",
                    "content": (
                        f"Research and report the '{category_label}' fields for {location}. "
                        "Use web search to find current, accurate information for this "
                        "SPECIFIC SUBURB, not the metro area as a whole -- do not answer from "
                        "memory alone. Every field needs a source_url and fetched_date "
                        f"(today is {date.today().isoformat()}) alongside its value."
                    ),
                }],
            )
            raw = json.loads(response.choices[0].message.content)
            last_error = None
            break
        except Exception as e:
            last_error = e
            if attempt == 0:
                await asyncio.sleep(2)
    if last_error is not None:
        print(
            f"WARNING: {category_label} failed after retry for {suburb_name}: "
            f"{type(last_error).__name__}: {last_error}",
            file=sys.stderr,
        )

    result: dict[str, StoredFieldValue] = {}
    for field_key, field_def in field_defs.items():
        schema_version = field_def["schema_version"]
        raw_field = raw.get(field_key)
        if raw_field is None:
            result[field_key] = StoredFieldValue(status=FieldStatus.UNRESOLVED, schema_version=schema_version)
            continue
        try:
            field_model = build_field_value_model(field_def)
            validated = field_model(**raw_field).model_dump()
            result[field_key] = StoredFieldValue(
                value=validated["value"],
                source_url=validated["source_url"],
                fetched_date=validated["fetched_date"],
                status=FieldStatus.VALID,
                schema_version=schema_version,
            )
        except ValidationError:
            result[field_key] = StoredFieldValue(status=FieldStatus.UNRESOLVED, schema_version=schema_version)
    return result


async def fetch_llm_fields_for_suburb(
    client: AsyncOpenAI, schema: dict, suburb_name: str, metro_label: str
) -> dict[str, dict[str, StoredFieldValue]]:
    """All LLM categories for one suburb, concurrently."""
    results = await asyncio.gather(*[
        fetch_llm_category(client, schema, cat, suburb_name, metro_label) for cat in LLM_CATEGORIES
    ])
    return dict(zip(LLM_CATEGORIES, results))


async def fetch_llm_fields_for_metro(
    schema: dict, suburb_names: list[str], metro_label: str
) -> dict[str, dict[str, dict[str, StoredFieldValue]]]:
    """Every suburb's LLM categories, concurrently across suburbs too --
    per the design doc's concurrency requirement. Returns
    {suburb_name: {category_key: {field_key: StoredFieldValue}}}."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set.")
    client = AsyncOpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    results = await asyncio.gather(*[
        fetch_llm_fields_for_suburb(client, schema, name, metro_label) for name in suburb_names
    ])
    return dict(zip(suburb_names, results))
