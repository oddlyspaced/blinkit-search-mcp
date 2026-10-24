import io
import json
from pathlib import Path

import pytest
from PIL import Image as PILImage
from mcp.server.mcpserver import Image

from blinkit_mcp import server
from blinkit_mcp.config import Location, load_location, save_location
from blinkit_mcp.errors import BlinkitError

FIXTURES = Path(__file__).parent / "fixtures"
GURUGRAM = Location("Sector 29, Gurugram", 28.4595, 77.0266, "43483")


def load(name):
    return json.loads((FIXTURES / name).read_text())


def png():
    buf = io.BytesIO()
    PILImage.new("RGB", (20, 20)).save(buf, "PNG")
    return buf.getvalue()


class FakeClient:
    def __init__(self, searches=(), product=None, json_responses=None, error=None):
        self.searches = list(searches)
        self.product_data = product
        self.json_responses = json_responses or {}
        self.error = error
        self.calls = []

    def _check(self):
        if self.error:
            raise self.error

    def search(self, query, lat, lon, next_url=None):
        self.calls.append(("search", query, lat, lon, next_url))
        self._check()
        return self.searches.pop(0)

    def product(self, product_id, lat, lon):
        self.calls.append(("product", product_id, lat, lon))
        self._check()
        return self.product_data

    def get_json(self, path, params, lat=None, lon=None):
        self.calls.append(("get_json", path, params))
        self._check()
        return self.json_responses[path]

    def get_bytes(self, url):
        self.calls.append(("get_bytes", url))
        return png()


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("BLINKIT_MCP_CONFIG", str(tmp_path / "config.json"))


@pytest.fixture
def fake(monkeypatch):
    def install(**kwargs):
        client = FakeClient(**kwargs)
        monkeypatch.setattr(server, "_client", client)
        return client

    return install


def kinds(client):
    return [c[0] for c in client.calls]


# --- location ---------------------------------------------------------------


def test_search_without_location_is_no_location(fake):
    client = fake()
    out = server.search_products("paneer")
    assert out["status"] == "no_location"
    assert "set_location" in out["message"]
    assert client.calls == []


def test_get_location_not_set_then_set(fake):
    fake()
    assert server.get_location()["status"] == "no_location"
    save_location(GURUGRAM)
    out = server.get_location()
    assert out["status"] == "ok"
    assert out["location"]["address"] == "Sector 29, Gurugram"


def test_set_location_with_coordinates_saves(fake):
    fake(searches=[load("search_milk_gurugram.json")])
    out = server.set_location(lat=28.4595, lon=77.0266)
    assert out["status"] == "ok" and out["serviceable"] is True
    assert load_location().merchant_id == "43483"


def test_set_location_address_returns_candidates(fake):
    client = fake(json_responses={"/location/autoSuggest": load("location_autosuggest.json")})
    out = server.set_location(address="HSR Layout sector 2 bengaluru")
    assert out["status"] == "choose_place"
    assert out["candidates"][0]["title"] == "HSR layout Sector 2"
    assert out["candidates"][0]["place_id"].startswith("ChIJ")
    assert load_location() is None
    assert "search" not in kinds(client)


def test_set_location_address_without_match(fake):
    fake(json_responses={"/location/autoSuggest": load("location_autosuggest_empty.json")})
    out = server.set_location(address="zzqxvkkq")
    assert out["status"] == "not_found"


def test_set_location_place_id_saves(fake):
    fake(
        json_responses={"/location/info": load("location_info_place.json")},
        searches=[load("search_milk_gurugram.json")],
    )
    out = server.set_location(place_id="ChIJabc")
    assert out["status"] == "ok"
    saved = load_location()
    assert saved.lat == pytest.approx(12.925317)
    assert saved.address.startswith("HSR layout Sector 2")


def test_set_location_unserviceable_saves_nothing(fake):
    fake(error=BlinkitError("not_serviceable", "Blinkit does not deliver to this location"))
    out = server.set_location(lat=33.5, lon=79.0)
    assert out["status"] == "not_serviceable"
    assert load_location() is None


def test_set_location_without_arguments_is_bad_input(fake):
    fake()
    assert server.set_location()["status"] == "bad_input"


# --- search -----------------------------------------------------------------


def test_search_uses_saved_location_headers(fake):
    save_location(GURUGRAM)
    client = fake(searches=[load("search_paneer_p1.json")])
    server.search_products("paneer", limit=5)
    assert client.calls[0][:4] == ("search", "paneer", 28.4595, 77.0266)


def test_search_coordinates_override_saved(fake):
    save_location(GURUGRAM)
    client = fake(searches=[load("search_paneer_p1.json")])
    out = server.search_products("paneer", limit=5, lat=12.9, lon=77.6)
    assert client.calls[0][2:4] == (12.9, 77.6)
    assert "warning" not in out


def test_search_follows_pages_and_filters(fake):
    save_location(GURUGRAM)
    p2 = load("search_paneer_p2.json")
    p2["response"].pop("pagination", None)
    client = fake(searches=[load("search_paneer_p1.json"), p2])
    out = server.search_products("paneer", limit=30)
    assert out["status"] == "found"
    assert out["count"] == 21
    ids = [p["product_id"] for p in out["products"]]
    assert "495737" not in ids and len(ids) == len(set(ids))
    assert client.calls[1][4].startswith("/v1/layout/search?offset=12")
    assert out["actual_query"] == "paneer"
    assert out["merchant_id"] == "43483"
    assert "warning" not in out


def test_search_limit_stops_paging(fake):
    save_location(GURUGRAM)
    client = fake(searches=[load("search_paneer_p1.json")])
    out = server.search_products("paneer", limit=5)
    assert out["count"] == 5 and len(client.calls) == 1


def test_search_stops_after_three_pages(fake):
    save_location(GURUGRAM)
    client = fake(searches=[load("search_nomatch.json")] * 5)
    server.search_products("xqzvbnm", limit=30)
    assert len(client.calls) == 3


def test_search_empty_has_reason(fake):
    save_location(GURUGRAM)
    nomatch = load("search_nomatch.json")
    nomatch["response"].pop("pagination", None)
    fake(searches=[nomatch])
    out = server.search_products("xqzvbnm")
    assert out["status"] == "no_match"
    assert out["count"] == 0 and out["products"] == []
    assert "xqzvbnm" in out["reason"]


def test_search_blank_query_is_bad_input(fake):
    save_location(GURUGRAM)
    assert server.search_products("   ")["status"] == "bad_input"


def test_store_change_adds_warning(fake):
    save_location(Location("Somewhere", 28.4595, 77.0266, "99999"))
    fake(searches=[load("search_paneer_p1.json")])
    out = server.search_products("paneer", limit=5)
    assert "99999" in out["warning"] and "43483" in out["warning"]


def test_blinkit_error_becomes_status_dict(fake):
    save_location(GURUGRAM)
    fake(error=BlinkitError("blocked", "Blinkit blocked the request"))
    assert server.search_products("paneer") == {"status": "blocked", "message": "Blinkit blocked the request"}


# --- product ------------------------------------------------------------------


def test_get_product_returns_attributes(fake):
    save_location(GURUGRAM)
    fake(product=load("product_329500.json"))
    out = server.get_product("329500")
    assert out["status"] == "ok"
    assert out["product"]["name"] == "Amul Fresh Malai Paneer"
    assert out["attributes"]["Shelf Life"] == "45 days"
    assert len(out["images"]) == 3
    assert "sponsored" not in out["product"]


def test_get_product_bad_id(fake):
    save_location(GURUGRAM)
    client = fake()
    assert server.get_product("../etc")["status"] == "bad_input"
    assert client.calls == []


# --- images -------------------------------------------------------------------


def test_view_images_returns_images(fake):
    save_location(GURUGRAM)
    fake(product=load("product_329500.json"))
    out = server.view_images(product_id="329500", indexes=[0])
    assert isinstance(out[0], str) and out[0].startswith("[0] https://cdn.grofers.com/")
    assert isinstance(out[1], Image)
    assert len(out) == 2


def test_view_images_default_is_whole_gallery_up_to_limit(fake):
    save_location(GURUGRAM)
    fake(product=load("product_329500.json"))
    out = server.view_images(product_id="329500")
    assert sum(isinstance(x, Image) for x in out) == 3


def test_view_images_index_out_of_range(fake):
    save_location(GURUGRAM)
    client = fake(product=load("product_329500.json"))
    out = server.view_images(product_id="329500", indexes=[5])
    assert json.loads(out[0])["status"] == "bad_input"
    assert "get_bytes" not in kinds(client)


def test_view_images_too_many(fake):
    client = fake()
    urls = [f"https://cdn.grofers.com/{i}.jpg" for i in range(5)]
    out = server.view_images(urls=urls)
    assert json.loads(out[0])["status"] == "bad_input"
    assert client.calls == []


def test_view_images_bad_host(fake):
    client = fake()
    out = server.view_images(urls=["https://cdn.grofers.com/a.jpg", "https://evil.example.com/a.jpg"])
    assert json.loads(out[0])["status"] == "bad_input"
    assert client.calls == []


def test_view_images_by_url_needs_no_location(fake):
    fake()
    out = server.view_images(urls=["https://cdn.grofers.com/a.jpg"])
    assert isinstance(out[1], Image)


def test_view_images_needs_exactly_one_source(fake):
    fake()
    assert json.loads(server.view_images()[0])["status"] == "bad_input"


# --- MCP wiring ---------------------------------------------------------------


@pytest.mark.anyio
async def test_tools_are_registered():
    names = {t.name for t in await server.mcp.list_tools()}
    assert names == {"set_location", "get_location", "search_products", "get_product", "view_images"}


# --- final review fixes -------------------------------------------------------


def test_search_limit_one_with_ad_first_is_found(fake):
    save_location(GURUGRAM)
    fake(searches=[load("search_milk_gurugram.json")])
    out = server.search_products("milk", limit=1)
    assert out["status"] == "found"
    assert out["count"] == 1
    assert out["products"][0]["matches_query"] is True


def test_search_fills_limit_with_matches_before_ads(fake):
    save_location(GURUGRAM)
    fake(searches=[load("search_paneer_p1.json")])
    out = server.search_products("paneer", limit=3)
    assert all(p["matches_query"] for p in out["products"])


def test_get_product_unstocked_has_note(fake):
    save_location(GURUGRAM)
    fake(product=load("product_unstocked.json"))
    out = server.get_product("329500")
    assert out["product"]["in_stock"] is False
    assert "not" in out["note"].lower() and "price" in out["note"].lower()


def test_get_product_missing_is_not_found(fake):
    save_location(GURUGRAM)
    fake(product=load("product_missing.json"))
    assert server.get_product("999999999")["status"] == "not_found"


def test_get_client_is_shared_across_threads(monkeypatch):
    import threading
    import time as _time

    created = []

    class SlowClient:
        def __init__(self):
            _time.sleep(0.05)
            created.append(self)

    monkeypatch.setattr(server, "_client", None)
    monkeypatch.setattr(server, "BlinkitClient", SlowClient)
    threads = [threading.Thread(target=server.get_client) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(created) == 1
