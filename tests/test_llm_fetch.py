import json
from pathlib import Path

import pytest

import llm_fetch
from models import FieldStatus
from tests.fakes import FakeAsyncOpenAI

SCHEMA_PATH = Path(__file__).parent.parent / "schema.json"


def load_schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)


@pytest.mark.asyncio
async def test_fetch_llm_category_valid_response():
    schema = load_schema()

    def handler(kwargs):
        return {
            "violent_crime_rate": {"value": 2.1, "source_url": "https://x.com", "fetched_date": "2026-08-17"},
            "property_crime_rate": {"value": 15.0, "source_url": "https://x.com", "fetched_date": "2026-08-17"},
            "safety_index": {"value": 78.0, "source_url": "https://x.com", "fetched_date": "2026-08-17"},
        }

    client = FakeAsyncOpenAI(handler=handler)
    result = await llm_fetch.fetch_llm_category(client, schema, "crime", "Meridian", "Boise, ID")

    assert result["violent_crime_rate"].status == FieldStatus.VALID
    assert result["violent_crime_rate"].value == 2.1
    assert result["safety_index"].value == 78.0


@pytest.mark.asyncio
async def test_fetch_llm_category_uses_the_cheap_model():
    schema = load_schema()
    seen_models = []

    def handler(kwargs):
        seen_models.append(kwargs["model"])
        return {
            "violent_crime_rate": {"value": 2.1, "source_url": "https://x.com", "fetched_date": "2026-08-17"},
            "property_crime_rate": {"value": 15.0, "source_url": "https://x.com", "fetched_date": "2026-08-17"},
            "safety_index": {"value": 78.0, "source_url": "https://x.com", "fetched_date": "2026-08-17"},
        }

    client = FakeAsyncOpenAI(handler=handler)
    await llm_fetch.fetch_llm_category(client, schema, "crime", "Meridian", "Boise, ID")

    assert seen_models == ["anthropic/claude-haiku-4.5"]


@pytest.mark.asyncio
async def test_fetch_llm_category_total_failure_marks_all_fields_unresolved():
    schema = load_schema()
    client = FakeAsyncOpenAI(handler=lambda kwargs: None)  # simulated API failure, both attempts

    result = await llm_fetch.fetch_llm_category(client, schema, "crime", "Meridian", "Boise, ID")

    assert all(f.status == FieldStatus.UNRESOLVED for f in result.values())
    assert set(result.keys()) == {"violent_crime_rate", "property_crime_rate", "safety_index"}


@pytest.mark.asyncio
async def test_fetch_llm_category_retries_once_then_succeeds():
    schema = load_schema()
    calls = {"n": 0}

    def handler(kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # first attempt fails
        return {
            "violent_crime_rate": {"value": 2.1, "source_url": "https://x.com", "fetched_date": "2026-08-17"},
            "property_crime_rate": {"value": 15.0, "source_url": "https://x.com", "fetched_date": "2026-08-17"},
            "safety_index": {"value": 78.0, "source_url": "https://x.com", "fetched_date": "2026-08-17"},
        }

    client = FakeAsyncOpenAI(handler=handler)
    result = await llm_fetch.fetch_llm_category(client, schema, "crime", "Meridian", "Boise, ID")

    assert calls["n"] == 2
    assert result["violent_crime_rate"].status == FieldStatus.VALID


@pytest.mark.asyncio
async def test_fetch_llm_category_bad_field_shape_marks_only_that_field_unresolved():
    schema = load_schema()

    def handler(kwargs):
        return {
            "violent_crime_rate": {"value": "not-a-number", "source_url": "https://x.com", "fetched_date": "2026-08-17"},
            "property_crime_rate": {"value": 15.0, "source_url": "https://x.com", "fetched_date": "2026-08-17"},
            "safety_index": {"value": 78.0, "source_url": "https://x.com", "fetched_date": "2026-08-17"},
        }

    client = FakeAsyncOpenAI(handler=handler)
    result = await llm_fetch.fetch_llm_category(client, schema, "crime", "Meridian", "Boise, ID")

    assert result["violent_crime_rate"].status == FieldStatus.UNRESOLVED
    assert result["property_crime_rate"].status == FieldStatus.VALID


@pytest.mark.asyncio
async def test_fetch_llm_category_only_sends_llm_sourced_fields():
    """The 'schools' category mixes source=llm (school_list_ratings) and
    source=api (school_locations, from Overpass) -- only the LLM-sourced
    field should appear in the request/response shape."""
    schema = load_schema()
    requested_fields = []

    def handler(kwargs):
        response_schema = kwargs["response_format"]["json_schema"]["schema"]
        requested_fields.extend(response_schema["properties"].keys())
        return {"school_list_ratings": {"value": "Meridian HS: 8/10", "source_url": "https://x.com", "fetched_date": "2026-08-17"}}

    client = FakeAsyncOpenAI(handler=handler)
    await llm_fetch.fetch_llm_category(client, schema, "schools", "Meridian", "Boise, ID")

    assert requested_fields == ["school_list_ratings"]


@pytest.mark.asyncio
async def test_fetch_llm_fields_for_metro_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    schema = load_schema()
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        await llm_fetch.fetch_llm_fields_for_metro(schema, ["Meridian"], "Boise, ID")


@pytest.mark.asyncio
async def test_fetch_llm_fields_for_suburb_covers_all_categories():
    schema = load_schema()

    def handler(kwargs):
        response_schema = kwargs["response_format"]["json_schema"]["schema"]
        return {
            key: {"value": "x" if props.get("type") != "number" else 1.0, "source_url": "https://x.com", "fetched_date": "2026-08-17"}
            for key, props in response_schema["properties"].items()
        }

    client = FakeAsyncOpenAI(handler=handler)
    result = await llm_fetch.fetch_llm_fields_for_suburb(client, schema, "Meridian", "Boise, ID")

    assert set(result.keys()) == set(llm_fetch.LLM_CATEGORIES)
