"""Unit tests mock the TIGERweb HTTP layer. One live smoke test at the bottom
hits the real TIGERweb API (no key required) against real Ada+Canyon County
data -- this is the "manual sanity-check against local knowledge" the design
doc requires before trusting enumeration for a new metro."""
import census


def test_enumerate_suburbs_dedupes_places_spanning_counties(monkeypatch):
    """Meridian intersects both Ada and Canyon County in real data -- must
    appear once in the result, not twice."""
    monkeypatch.setattr(
        census,
        "fetch_county_geometry",
        lambda state_fips, county_fips: {
            "attributes": {"NAME": f"County {county_fips}"},
            "geometry": {"rings": [[[0, 0]]]},
            "spatialReference": {"wkid": 4326},
        },
    )

    def fake_places(geometry, spatial_ref, layer_id):
        if layer_id == census.INCORPORATED_PLACES_LAYER:
            return [
                {"NAME": "Meridian city", "STATE": "16", "GEOID": "1650770", "PLACE": "50770", "INTPTLAT": "+43.6121", "INTPTLON": "-116.3915"},
                {"NAME": "Boise City city", "STATE": "16", "GEOID": "1608830", "PLACE": "08830", "INTPTLAT": "+43.6150", "INTPTLON": "-116.2023"},
            ]
        return []  # no CDPs in this fake county

    monkeypatch.setattr(census, "_places_intersecting", fake_places)

    result = census.enumerate_suburbs("16", [{"name": "Ada", "fips": "001"}, {"name": "Canyon", "fips": "027"}])

    names = [p["name"] for p in result]
    assert names.count("Meridian city") == 1
    assert "Boise City city" in names


def test_enumerate_suburbs_includes_incorporated_and_cdp(monkeypatch):
    monkeypatch.setattr(
        census,
        "fetch_county_geometry",
        lambda state_fips, county_fips: {
            "attributes": {},
            "geometry": {"rings": [[[0, 0]]]},
            "spatialReference": {"wkid": 4326},
        },
    )

    def fake_places(geometry, spatial_ref, layer_id):
        if layer_id == census.INCORPORATED_PLACES_LAYER:
            return [{"NAME": "Eagle city", "STATE": "16", "GEOID": "1624070", "PLACE": "24070", "INTPTLAT": "+43.6955", "INTPTLON": "-116.3540"}]
        return [{"NAME": "Avimor CDP", "STATE": "16", "GEOID": "1603760", "PLACE": "03760", "INTPTLAT": "+43.8460", "INTPTLON": "-116.2560"}]

    monkeypatch.setattr(census, "_places_intersecting", fake_places)

    result = census.enumerate_suburbs("16", [{"name": "Ada", "fips": "001"}])
    kinds = {p["name"]: p["kind"] for p in result}
    assert kinds["Eagle city"] == "incorporated"
    assert kinds["Avimor CDP"] == "cdp"


def test_enumerate_suburbs_excludes_neighboring_state_places(monkeypatch):
    """A county polygon touching a state-line river can spatially intersect
    a neighboring state's places -- caught live: Nez Perce County, ID
    (bordering the Snake River / Washington) pulled in Clarkston and Asotin,
    both actually STATE=53 (Washington). Only STATE==state_fips belongs."""
    monkeypatch.setattr(
        census,
        "fetch_county_geometry",
        lambda state_fips, county_fips: {
            "attributes": {}, "geometry": {"rings": [[[0, 0]]]}, "spatialReference": {"wkid": 4326},
        },
    )

    def fake_places(geometry, spatial_ref, layer_id):
        if layer_id == census.INCORPORATED_PLACES_LAYER:
            return [
                {"NAME": "Lewiston city", "STATE": "16", "GEOID": "1646540", "PLACE": "46540", "INTPTLAT": "+46.4004", "INTPTLON": "-117.0177"},
                {"NAME": "Clarkston city", "STATE": "53", "GEOID": "5312630", "PLACE": "12630", "INTPTLAT": "+46.4165", "INTPTLON": "-117.0466"},
                {"NAME": "Asotin city", "STATE": "53", "GEOID": "5303075", "PLACE": "03075", "INTPTLAT": "+46.3404", "INTPTLON": "-117.0466"},
            ]
        return []

    monkeypatch.setattr(census, "_places_intersecting", fake_places)

    result = census.enumerate_suburbs("16", [{"name": "Nez Perce County", "fips": "069"}])
    names = {p["name"] for p in result}

    assert names == {"Lewiston city"}
    assert "Clarkston city" not in names
    assert "Asotin city" not in names


def test_live_enumerate_nez_perce_county_excludes_washington_places():
    """Live regression test for the same bug, against the real TIGERweb
    data that surfaced it."""
    result = census.enumerate_suburbs("16", [{"name": "Nez Perce County", "fips": "069"}])
    names = {p["name"] for p in result}

    assert "Lewiston city" in names
    assert "Clarkston city" not in names
    assert "Asotin city" not in names
    for p in result:
        assert p["lon"] > -117.1, f"{p['name']} looks like it's across the state line (WA)"


def test_fetch_acs_batch_requires_api_key(monkeypatch):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    try:
        census.fetch_acs_batch("16", ["08830"], ["B01003_001E"])
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "CENSUS_API_KEY" in str(e)


def test_live_enumerate_ada_and_canyon_county_matches_local_knowledge():
    """Live TIGERweb call, no API key required. Verifies the real place list
    for Treasure Valley matches known suburbs -- this IS the manual
    sanity-check the design doc requires before locking a new metro's
    suburb list."""
    result = census.enumerate_suburbs(
        "16",
        [{"name": "Ada County", "fips": "001"}, {"name": "Canyon County", "fips": "027"}],
    )
    names = {p["name"] for p in result}

    expected_known_suburbs = {
        "Boise City city", "Meridian city", "Nampa city", "Caldwell city",
        "Eagle city", "Kuna city", "Star city", "Garden City city",
        "Middleton city",
    }
    missing = expected_known_suburbs - names
    assert not missing, f"Known Treasure Valley suburbs missing from enumeration: {missing}"

    # Meridian, Nampa, and Star span both counties -- confirms dedup works
    # against real (not fake) TIGERweb data too.
    assert len(names) == len(result), "duplicate suburb entries in live result"

    # Every suburb needs real coordinates for overpass.py's distance calc --
    # Idaho is roughly lat 42-49, lon -117 to -111.
    for p in result:
        assert 42.0 < p["lat"] < 49.0, f"{p['name']} lat out of Idaho range: {p['lat']}"
        assert -117.0 < p["lon"] < -111.0, f"{p['name']} lon out of Idaho range: {p['lon']}"
