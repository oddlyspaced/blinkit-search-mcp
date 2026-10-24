import json
from pathlib import Path

import pytest

from blinkit_mcp.errors import BlinkitError
from blinkit_mcp.location import Place, Suggestion, check_serviceable, place_location, suggest_places

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


class FakeClient:
    def __init__(self, json_responses=None, search_response=None, search_error=None):
        self.json_responses = dict(json_responses or {})
        self.search_response = search_response
        self.search_error = search_error
        self.calls = []

    def get_json(self, path, params, lat=None, lon=None):
        self.calls.append((path, params))
        return self.json_responses[path]

    def search(self, query, lat, lon, next_url=None):
        self.calls.append(("search", query, lat, lon))
        if self.search_error:
            raise self.search_error
        return self.search_response


def test_suggest_places_returns_candidates():
    client = FakeClient({"/location/autoSuggest": load("location_autosuggest.json")})
    got = suggest_places(client, "HSR Layout sector 2 bengaluru")
    assert 1 <= len(got) <= 5
    assert got[0] == Suggestion(
        title="HSR layout Sector 2",
        subtitle="1st Stage, BTM 1st Stage, Bengaluru, Karnataka, India",
        place_id=got[0].place_id,
    )
    assert got[0].place_id.startswith("ChIJ")
    path, params = client.calls[0]
    assert params["query"] == "HSR Layout sector 2 bengaluru"
    assert "lat" in params and "lng" in params  # autoSuggest returns HTTP 400 without a bias point


def test_suggest_places_no_result_is_empty():
    client = FakeClient({"/location/autoSuggest": load("location_autosuggest_empty.json")})
    assert suggest_places(client, "zzqxvkkq") == []


def test_place_location_returns_coordinates():
    client = FakeClient({"/location/info": load("location_info_place.json")})
    place = place_location(client, "ChIJabc")
    assert place.lat == pytest.approx(12.925317) and place.lon == pytest.approx(77.6166666)
    assert place.address.startswith("HSR layout Sector 2")
    assert client.calls[0] == ("/location/info", {"place_id": "ChIJabc"})


def test_place_location_zero_coordinates_is_not_found():
    data = load("location_info_place.json")
    data["coordinate"] = {"lat": 0, "lon": 0}
    client = FakeClient({"/location/info": data})
    with pytest.raises(BlinkitError) as e:
        place_location(client, "ChIJabc")
    assert e.value.code == "not_found"


def test_serviceable_returns_merchant_id():
    client = FakeClient(search_response=load("search_milk_gurugram.json"))
    assert check_serviceable(client, 28.4595, 77.0266) == "43483"
    assert client.calls[0] == ("search", "milk", 28.4595, 77.0266)


def test_unserviceable_raises():
    client = FakeClient(search_error=BlinkitError("not_serviceable", "Blinkit does not deliver to this location"))
    with pytest.raises(BlinkitError) as e:
        check_serviceable(client, 33.5, 79.0)
    assert e.value.code == "not_serviceable"


def test_search_without_cards_is_unserviceable():
    client = FakeClient(search_response={"is_success": True, "response": {"snippets": []}})
    with pytest.raises(BlinkitError) as e:
        check_serviceable(client, 33.5, 79.0)
    assert e.value.code == "not_serviceable"
