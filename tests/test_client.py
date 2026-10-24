import pytest

from blinkit_mcp.client import BlinkitClient
from blinkit_mcp.errors import BlinkitError

LAT, LON = 28.4595, 77.0266


class FakeResponse:
    def __init__(self, status_code=200, text='{"is_success": true, "response": {}}'):
        self.status_code = status_code
        self.text = text
        self.content = text.encode()
        self.headers = {}


class FakeSession:
    def __init__(self, responses=None, exc=None):
        self.responses = list(responses or [])
        self.exc = exc
        self.calls = []

    def request(self, method, url, headers=None, json=None, params=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "json": json, "params": params})
        if self.exc:
            raise self.exc
        return self.responses.pop(0) if self.responses else FakeResponse()


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def make(responses=None, exc=None):
    clock = FakeClock()
    session = FakeSession(responses, exc)
    return BlinkitClient(session=session, sleep=clock.sleep, clock=clock.time), session, clock


def test_sends_location_headers():
    client, session, _ = make()
    client.search("paneer", LAT, LON)
    h = session.calls[-1]["headers"]
    assert h["lat"] == "28.4595" and h["lon"] == "77.0266"
    assert h["app_client"] == "consumer_web"
    assert h["origin"] == "https://blinkit.com"


def test_search_url_and_body():
    client, session, _ = make()
    client.search("paneer", LAT, LON)
    call = session.calls[-1]
    assert call["method"] == "POST"
    assert call["url"] == "https://blinkit.com/v1/layout/search?q=paneer&search_type=type_to_search"
    assert call["json"] == {}


def test_search_query_is_url_encoded():
    client, session, _ = make()
    client.search("kasuri methi & co", LAT, LON)
    assert "q=kasuri+methi+%26+co" in session.calls[-1]["url"]


def test_next_url_is_used_as_is():
    client, session, _ = make()
    nxt = "/v1/layout/search?offset=12&limit=12&q=paneer"
    client.search("paneer", LAT, LON, next_url=nxt)
    assert session.calls[-1]["url"] == "https://blinkit.com" + nxt


def test_product_url():
    client, session, _ = make()
    client.product("329500", LAT, LON)
    assert session.calls[-1]["method"] == "POST"
    assert session.calls[-1]["url"] == "https://blinkit.com/v1/layout/product/329500"


def test_rate_limit_sleeps_between_calls():
    client, _, clock = make()
    client.search("a", LAT, LON)
    client.search("b", LAT, LON)
    assert clock.sleeps and abs(sum(clock.sleeps) - 1.0) < 1e-6


def test_403_retries_once_then_blocked():
    client, session, clock = make([FakeResponse(403, "<html>"), FakeResponse(403, "<html>")])
    with pytest.raises(BlinkitError) as e:
        client.search("paneer", LAT, LON)
    assert e.value.code == "blocked"
    assert len(session.calls) == 2
    assert 3 in clock.sleeps


def test_html_200_is_blocked():
    client, _, _ = make([FakeResponse(200, "<!DOCTYPE html><title>Error</title>")] * 2)
    with pytest.raises(BlinkitError) as e:
        client.search("paneer", LAT, LON)
    assert e.value.code == "blocked"


def test_404_is_not_found():
    client, _, _ = make([FakeResponse(404, "<h1>no Route</h1>")])
    with pytest.raises(BlinkitError) as e:
        client.product("1", LAT, LON)
    assert e.value.code == "not_found"


def test_is_success_false_is_upstream_changed():
    client, _, _ = make([FakeResponse(200, '{"is_success": false}')])
    with pytest.raises(BlinkitError) as e:
        client.search("paneer", LAT, LON)
    assert e.value.code == "upstream_changed"


def test_get_json_does_not_require_is_success():
    client, _, _ = make([FakeResponse(200, '{"ui_data": {}}')])
    assert client.get_json("/location/autoSuggest", {"query": "x"}) == {"ui_data": {}}


def test_transport_exception_is_network():
    client, _, _ = make(exc=OSError("connection reset"))
    with pytest.raises(BlinkitError) as e:
        client.search("paneer", LAT, LON)
    assert e.value.code == "network"


def test_get_bytes_sends_no_location_headers():
    client, session, _ = make([FakeResponse(200, "IMG")])
    assert client.get_bytes("https://cdn.grofers.com/a.jpg") == b"IMG"
    assert "lat" not in session.calls[-1]["headers"]


def test_400_location_not_serviceable():
    client, _, _ = make([FakeResponse(400, '{"error":"location not serviceable"}')])
    with pytest.raises(BlinkitError) as e:
        client.search("milk", 33.5, 79.0)
    assert e.value.code == "not_serviceable"


def test_rate_limit_holds_across_threads():
    import threading
    import time as _time

    sent = []

    class SlowSession:
        def request(self, method, url, **kwargs):
            sent.append(_time.monotonic())
            _time.sleep(0.01)
            return FakeResponse()

    client = BlinkitClient(session=SlowSession(), min_interval=0.1)
    threads = [threading.Thread(target=client.search, args=("x", LAT, LON)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    sent.sort()
    gaps = [b - a for a, b in zip(sent, sent[1:])]
    assert len(sent) == 4 and min(gaps) >= 0.095
