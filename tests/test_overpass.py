"""Unit tests mock the Overpass HTTP layer -- no live test here, unlike
census.py. During development a burst of live Overpass calls triggered a
real HTTP 429 from the public instance within minutes; a live test in the
regular suite would be flaky by design. The retry/backoff path itself is
tested against a fake 429-then-success sequence instead."""
import json
import urllib.error

import pytest

import overpass


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_haversine_known_distance():
    # Boise, ID to Meridian, ID -- roughly 9-10 miles apart.
    d = overpass.haversine_miles(43.6150, -116.2023, 43.6121, -116.3915)
    assert 9 <= d <= 11


def test_nearest_distance_returns_none_for_empty_pois():
    assert overpass.nearest_distance_mi(43.6, -116.2, []) is None


def test_nearest_distance_picks_closest():
    pois = [
        overpass.Poi(name="far", lat=44.0, lon=-117.0),
        overpass.Poi(name="near", lat=43.61, lon=-116.20),
    ]
    d = overpass.nearest_distance_mi(43.6150, -116.2023, pois)
    assert d < 1.0  # the "near" POI is essentially at the query point


def test_metro_bbox_unions_multiple_counties():
    geometries = [
        {"rings": [[[-116.5, 43.4], [-116.3, 43.4], [-116.3, 43.6], [-116.5, 43.6]]]},
        {"rings": [[[-116.7, 43.5], [-116.5, 43.5], [-116.5, 43.7], [-116.7, 43.7]]]},
    ]
    bbox = overpass.metro_bbox(geometries)
    south, west, north, east = (float(x) for x in bbox.split(","))
    assert south == 43.4
    assert west == -116.7
    assert north == 43.7
    assert east == -116.3


def test_fetch_category_pois_empty_result_is_confirmed_absent(monkeypatch):
    """Zero POIs (query succeeded) must not raise -- caller treats this as
    confirmed_absent, distinct from a raised OverpassQueryFailed."""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=30: FakeResponse({"elements": []}),
    )
    pois = overpass.fetch_category_pois("pickleball", "43.35,-116.75,43.75,-116.15")
    assert pois == []


def test_fetch_category_pois_retries_on_429_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(req, timeout=30):
        calls["n"] += 1
        if calls["n"] < 2:
            raise urllib.error.HTTPError(url="", code=429, msg="rate limited", hdrs=None, fp=None)
        return FakeResponse({"elements": [{"lat": 43.6, "lon": -116.2, "tags": {"name": "Test"}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda s: None)  # don't actually wait in tests

    pois = overpass.fetch_category_pois("pickleball", "43.35,-116.75,43.75,-116.15")
    assert len(pois) == 1
    assert calls["n"] == 2


def test_fetch_category_pois_raises_after_exhausting_retries(monkeypatch):
    def fake_urlopen(req, timeout=30):
        raise urllib.error.HTTPError(url="", code=429, msg="rate limited", hdrs=None, fp=None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda s: None)

    with pytest.raises(overpass.OverpassQueryFailed):
        overpass.fetch_category_pois("pickleball", "43.35,-116.75,43.75,-116.15")
