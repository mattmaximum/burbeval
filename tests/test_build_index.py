from build_index import build_index
from models import MetroRecord


def test_empty_metros_shows_empty_state():
    html = build_index([])
    assert "No metros evaluated yet" in html


def test_lists_metros_sorted_by_label():
    metros = [
        MetroRecord(metro_slug="denver-co", metro_label="Denver, CO", suburbs={"a": {"name": "A", "categories": {}}}),
        MetroRecord(metro_slug="boise-id", metro_label="Boise, ID", suburbs={"a": {"name": "A", "categories": {}}, "b": {"name": "B", "categories": {}}}),
    ]
    html = build_index(metros)
    assert html.index("Boise, ID") < html.index("Denver, CO")
    assert "2 suburbs" in html
    assert "1 suburbs" in html
