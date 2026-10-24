"""HTTP access to Blinkit's private web API.

All Blinkit requests go through BlinkitClient. It sends a Chrome TLS
fingerprint (plain HTTP clients get HTTP 403), adds the location headers,
spaces requests at least `min_interval` seconds apart, and maps failures to
BlinkitError codes.
"""

import json
import threading
import time
from urllib.parse import urlencode

from .errors import BLOCKED, NETWORK, NOT_FOUND, NOT_SERVICEABLE, UPSTREAM_CHANGED, BlinkitError

BASE_URL = "https://blinkit.com"
BLOCK_RETRY_DELAY = 3.0
TIMEOUT = 20


def _default_session():
    from curl_cffi import requests

    return requests.Session(impersonate="chrome")


class BlinkitClient:
    def __init__(self, session=None, min_interval: float = 1.0, sleep=time.sleep, clock=time.monotonic):
        self._session = session
        self._warmed = session is not None  # injected sessions need no cookie warm-up
        self.min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last = None
        # MCPServer runs sync tools in worker threads; one lock keeps the
        # spacing between requests and the one-time warm-up correct.
        self._lock = threading.RLock()

    @property
    def session(self):
        with self._lock:
            if self._session is None:
                self._session = _default_session()
            if not self._warmed:
                self._warmed = True
                self._send("GET", BASE_URL + "/", {}, None, None)
            return self._session

    def search(self, query: str, lat: float, lon: float, next_url: str | None = None) -> dict:
        if next_url:
            url = BASE_URL + next_url
        else:
            url = f"{BASE_URL}/v1/layout/search?" + urlencode({"q": query, "search_type": "type_to_search"})
        return self._api("POST", url, lat, lon)

    def product(self, product_id: str, lat: float, lon: float) -> dict:
        # An unknown id returns is_success=false; parse_product reports not_found.
        resp = self._request("POST", f"{BASE_URL}/v1/layout/product/{product_id}", self._headers(lat, lon), {}, None)
        return self._decode(resp, require_success=False)

    def get_json(self, path: str, params: dict, lat: float | None = None, lon: float | None = None) -> dict:
        resp = self._request("GET", BASE_URL + path, self._headers(lat, lon), None, params)
        return self._decode(resp, require_success=False)

    def get_bytes(self, url: str) -> bytes:
        return self._request("GET", url, {}, None, None).content

    def _api(self, method: str, url: str, lat: float, lon: float) -> dict:
        resp = self._request(method, url, self._headers(lat, lon), {}, None)
        return self._decode(resp, require_success=True)

    @staticmethod
    def _headers(lat, lon) -> dict:
        h = {
            "app_client": "consumer_web",
            "content-type": "application/json",
            "origin": BASE_URL,
        }
        if lat is not None and lon is not None:
            h["lat"] = str(lat)
            h["lon"] = str(lon)
        return h

    def _request(self, method, url, headers, body, params):
        session = self.session
        for attempt in range(2):
            resp = self._send(method, url, headers, body, params, session)
            if resp.status_code == 403 or (resp.status_code == 200 and _looks_like_html(resp.text)):
                if attempt == 0:
                    self._sleep(BLOCK_RETRY_DELAY)
                    continue
                raise BlinkitError(BLOCKED, f"Blinkit blocked the request ({resp.status_code}) for {url}")
            if resp.status_code == 400 and "not serviceable" in resp.text:
                raise BlinkitError(NOT_SERVICEABLE, "Blinkit does not deliver to this location")
            if resp.status_code == 404:
                raise BlinkitError(NOT_FOUND, f"Blinkit returned 404 for {url}")
            if resp.status_code >= 400:
                raise BlinkitError(NETWORK, f"Blinkit returned HTTP {resp.status_code} for {url}")
            return resp
        raise AssertionError("unreachable")

    def _send(self, method, url, headers, body, params, session=None):
        session = session or self._session
        with self._lock:
            if self._last is not None:
                wait = self.min_interval - (self._clock() - self._last)
                if wait > 0:
                    self._sleep(wait)
            try:
                return session.request(method, url, headers=headers, json=body, params=params, timeout=TIMEOUT)
            except Exception as exc:  # curl_cffi raises its own error types
                raise BlinkitError(NETWORK, f"request to {url} failed: {exc}") from exc
            finally:
                self._last = self._clock()

    @staticmethod
    def _decode(resp, require_success: bool) -> dict:
        try:
            data = json.loads(resp.text)
        except ValueError:
            raise BlinkitError(UPSTREAM_CHANGED, "Blinkit returned a response that is not JSON")
        if require_success and not (isinstance(data, dict) and data.get("is_success")):
            raise BlinkitError(UPSTREAM_CHANGED, "Blinkit response has no is_success=true")
        return data


def _looks_like_html(text: str) -> bool:
    return text.lstrip()[:1] == "<"
