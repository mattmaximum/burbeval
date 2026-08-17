import pytest

from metros import MetroConfigError, slugify_metro, validate_metro_entry

VALID_ENTRY = {
    "label": "Boise, ID",
    "state": "ID",
    "state_fips": "16",
    "counties": [{"name": "Ada County", "fips": "001"}],
}


def test_valid_entry_passes():
    validate_metro_entry("boise-id", VALID_ENTRY)  # no raise


def test_missing_label_fails():
    entry = {**VALID_ENTRY, "label": ""}
    with pytest.raises(MetroConfigError, match="label"):
        validate_metro_entry("boise-id", entry)


def test_bad_state_code_fails():
    entry = {**VALID_ENTRY, "state": "Idaho"}
    with pytest.raises(MetroConfigError, match="state"):
        validate_metro_entry("boise-id", entry)


def test_lowercase_state_code_fails():
    entry = {**VALID_ENTRY, "state": "id"}
    with pytest.raises(MetroConfigError, match="state"):
        validate_metro_entry("boise-id", entry)


def test_bad_state_fips_fails():
    entry = {**VALID_ENTRY, "state_fips": "X6"}
    with pytest.raises(MetroConfigError, match="state_fips"):
        validate_metro_entry("boise-id", entry)


def test_empty_counties_fails():
    entry = {**VALID_ENTRY, "counties": []}
    with pytest.raises(MetroConfigError, match="counties"):
        validate_metro_entry("boise-id", entry)


def test_county_missing_fips_fails():
    entry = {**VALID_ENTRY, "counties": [{"name": "Ada County"}]}
    with pytest.raises(MetroConfigError, match="fips"):
        validate_metro_entry("boise-id", entry)


def test_county_bad_fips_length_fails():
    entry = {**VALID_ENTRY, "counties": [{"name": "Ada County", "fips": "1"}]}
    with pytest.raises(MetroConfigError, match="fips"):
        validate_metro_entry("boise-id", entry)


def test_slugify_metro():
    assert slugify_metro("Boise, ID") == "boise-id"
    assert slugify_metro("Coeur d'Alene, ID") == "coeur-d-alene-id"
