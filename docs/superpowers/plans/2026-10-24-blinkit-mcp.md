# Blinkit MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local, read-only MCP server that searches Blinkit at a saved address and returns product data, product details, and product images.

**Architecture:** One HTTP client (`curl_cffi`, Chrome TLS fingerprint) sends all Blinkit requests with rate limiting and error mapping. Pure parser functions convert Blinkit JSON to small dataclasses. A FastMCP server over stdio exposes five tools and keeps the location in a JSON config file.

**Tech Stack:** Python 3.12+, `uv`, `mcp` (FastMCP), `curl_cffi`, `Pillow`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-10-24-blinkit-mcp-design.md`. Read it first. Section 7 has the Blinkit response formats.

## Global Constraints

- Read-only. No login, cart, or order calls.
- All Blinkit HTTP goes through `BlinkitClient`. Use `curl_cffi` with `impersonate="chrome"`. Plain `requests`/`httpx` get HTTP 403.
- Headers on every Blinkit call: `lat`, `lon`, `app_client: consumer_web`, `content-type: application/json`, `origin: https://blinkit.com`.
- Rate limit: minimum 1.0 s between requests. At most one retry after a block, after a 3 s delay.
- Error codes (exact strings): `no_location`, `blocked`, `not_serviceable`, `not_found`, `upstream_changed`, `network`, `bad_input`.
- Search status values (exact strings): `found`, `all_sold_out`, `no_match`.
- Prices are `float` in INR.
- Config path: `$BLINKIT_MCP_CONFIG`, else `~/.config/blinkit-mcp/config.json`.
- Images: only host `cdn.grofers.com`. Long side at most 1500 px. At most 4 images per call.
- All knowledge of Blinkit response formats is in `parsers.py`.
- Transport: stdio.

## Review Focus

1. A price like "₹1,299" and a card with no `mrp` field (5 of 12 cards on "paneer" page 1). Expect `1299.0`, and `mrp == price` with `discount_pct == 0`. Test: Task 2.
2. A config file that is empty or not valid JSON. Expect "location not set", not a crash. Test: Task 4.
3. HTTP 200 with an HTML body (bot page) instead of JSON. Expect `blocked`, not a JSON decode error. Test: Task 1.
4. A search where only ads come back. Expect `no_match` and no products. Test: Task 2.
5. `view_images` with a gallery index out of range, or a URL that is not on `cdn.grofers.com`. Expect `bad_input` with a message, and no download. Test: Task 5.

---

## File Structure

```
pyproject.toml
README.md
src/blinkit_mcp/__init__.py
src/blinkit_mcp/errors.py      # BlinkitError and error codes
src/blinkit_mcp/client.py      # HTTP session, headers, rate limit, error mapping
src/blinkit_mcp/models.py      # dataclasses shared by parsers and server
src/blinkit_mcp/parsers.py     # Blinkit JSON -> models (only file that knows formats)
src/blinkit_mcp/config.py      # load/save location
src/blinkit_mcp/location.py    # address -> coordinates, serviceability
src/blinkit_mcp/images.py      # download, validate host, resize
src/blinkit_mcp/server.py      # FastMCP tools, main()
scripts/capture_fixtures.py    # saves live responses into tests/fixtures
tests/fixtures/*.json
tests/test_client.py
tests/test_parsers.py
tests/test_config.py
tests/test_location.py
tests/test_images.py
tests/test_server.py
tests/test_live.py             # runs only when BLINKIT_LIVE=1
```

---

### Task 1: Project setup, errors, HTTP client, fixtures

**Files:**
- Create: `pyproject.toml`, `src/blinkit_mcp/__init__.py`, `src/blinkit_mcp/errors.py`, `src/blinkit_mcp/client.py`, `scripts/capture_fixtures.py`, `tests/test_client.py`, `tests/fixtures/*.json`, `.gitignore`

**Interfaces:**
- Produces:
  - `class BlinkitError(Exception)` with attributes `code: str`, `message: str`; constructor `BlinkitError(code, message)`.
  - `class BlinkitClient(session=None, min_interval: float = 1.0, sleep=time.sleep)`
    - `search(query: str, lat: float, lon: float, next_url: str | None = None) -> dict`: POST `/v1/layout/search?q=<query>&search_type=type_to_search` with body `{}`. If `next_url` is given, POST to `https://blinkit.com` + `next_url` instead.
    - `product(product_id: str, lat: float, lon: float) -> dict`: POST `/v1/layout/product/<id>`, body `{}`.
    - `get_json(path: str, params: dict, lat: float | None = None, lon: float | None = None) -> dict`: GET.
    - `get_bytes(url: str) -> bytes`: GET any URL, no Blinkit headers.
  - `session` is any object with `.request(method, url, headers=..., json=..., params=..., timeout=...)` returning an object with `.status_code`, `.text`, `.content`, `.headers`. Default: `curl_cffi.requests.Session(impersonate="chrome")`, with one `GET https://blinkit.com/` before the first API call.

- [ ] **Step 1: Set up the project**

`git init`. Create `pyproject.toml` (name `blinkit-mcp`, `requires-python = ">=3.12"`, deps `mcp`, `curl_cffi`, `Pillow`; dev group `pytest`; script `blinkit-mcp = "blinkit_mcp.server:main"`; src layout). `.gitignore`: `.venv/`, `__pycache__/`. Run `uv sync`.
Expected: `uv run python -c "import mcp, curl_cffi, PIL"` exits 0.

- [ ] **Step 2: Copy the recon responses into fixtures**

From `/private/tmp/claude-501/-Users-hardik-Projects-Misc-Random-blinkit-mcp/90a18c70-2a59-48ef-8fae-b3d86e788be3/scratchpad/`:
- `search.json` → `tests/fixtures/search_paneer_p1.json`
- `v1_layout_search.json` → `tests/fixtures/search_paneer_p2.json`
- `v1_layout_product_329500.json` → `tests/fixtures/product_329500.json`

If these files are gone, run Step 6 first and replace the exact values in Task 2 and Task 3 tests with the new values.

- [ ] **Step 3: Write the failing tests** in `tests/test_client.py`, with a `FakeSession` that returns queued responses and records calls:

```python
def test_sends_location_headers():          # headers lat="28.4595", lon="77.0266", app_client="consumer_web"
def test_search_url_and_body():              # POST .../v1/layout/search?q=paneer&search_type=type_to_search, json == {}
def test_next_url_is_used_as_is():           # url == "https://blinkit.com" + next_url
def test_rate_limit_sleeps_between_calls():  # fake clock; second call sleeps ~1.0 s
def test_403_retries_once_then_blocked():    # two 403s -> BlinkitError.code == "blocked"; exactly 2 requests; sleep(3) called
def test_html_200_is_blocked():              # status 200, text "<!DOCTYPE html>..." -> code "blocked"
def test_404_is_not_found():                 # code "not_found"
def test_is_success_false_is_upstream_changed():
def test_transport_exception_is_network():   # session raises -> code "network"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/test_client.py -v`
Expected: FAIL (import error).

- [ ] **Step 5: Implement `errors.py` and `client.py`**

Error mapping order: transport exception → `network`; 403 → retry once, then `blocked`; 404 → `not_found`; other status ≥ 400 → `network`; body not JSON → `blocked` if it starts with `<`, else `upstream_changed`; JSON with `is_success == false` → `upstream_changed`. `/location/*` responses have no `is_success`; do not require it.

- [ ] **Step 6: Write `scripts/capture_fixtures.py`**

Uses `BlinkitClient`. Saves into `tests/fixtures/`:
- `search_nomatch.json`: query `"xqzvbnm"` at 28.4595, 77.0266
- `search_unserviceable.json`: query `"milk"` at 26.9, 70.9
- `search_milk_gurugram.json`: query `"milk"` at 28.4595, 77.0266
- `product_unstocked.json`: product `329500` at 26.9, 70.9 (if the call raises, save `{"error": code}`)

Run: `uv run python scripts/capture_fixtures.py`
Expected: 4 files written. Print, for each search file, the count of organic and ad cards (spec 7.1 fields).
Stop and report to the user if `search_unserviceable.json` has organic cards. Task 4's serviceability rule depends on it having none.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_client.py -v`
Expected: 9 passed.

- [ ] **Step 8: Commit**

`git add -A && git commit -m "feat: add Blinkit HTTP client and fixtures"`

---

### Task 2: Search parser and filter

**Files:**
- Create: `src/blinkit_mcp/models.py`, `src/blinkit_mcp/parsers.py`, `tests/test_parsers.py`

**Interfaces:**
- Produces (`models.py`, all `@dataclass`):
  - `Product(product_id: str, name: str, brand: str | None, pack_size: str | None, price: float | None, mrp: float | None, discount_pct: int, in_stock: bool, inventory: int | None, image_url: str | None, url: str, product_type: str | None, sponsored: bool, merchant_id: str | None)`
  - `SearchPage(products: list[Product], actual_query: str | None, next_url: str | None)`. `products` includes ads, not filtered.
- Produces (`parsers.py`):
  - `parse_price(text: str | None) -> float | None`
  - `product_url(product_id: str, name: str) -> str`: `https://blinkit.com/prn/<slug>/prid/<id>`, slug = name lowercased, runs of non-alphanumerics → `-`, trimmed.
  - `parse_search_page(data: dict) -> SearchPage`
  - `filter_results(products: list[Product]) -> list[Product]`: spec 8.3 filter rule.
  - `search_status(kept: list[Product]) -> str`: `no_match` if no organic product, `all_sold_out` if none in stock, else `found`.

- [ ] **Step 1: Write the failing tests** in `tests/test_parsers.py`:

```python
def test_parse_price():
    assert parse_price("₹95") == 95.0
    assert parse_price("₹1,299") == 1299.0
    assert parse_price(None) is None

def test_search_page1_fields():
    page = parse_search_page(load("search_paneer_p1.json"))
    assert len(page.products) == 12
    p = page.products[0]
    assert (p.product_id, p.name, p.brand, p.pack_size) == ("686510", "Pride of Cows Low Fat High Protein Paneer", "Pride of Cows", "200 g")
    assert (p.price, p.mrp, p.discount_pct) == (219.0, 235.0, 6)   # floor((235-219)/235*100)
    assert p.sponsored is True and p.product_type == "Paneer"
    assert p.in_stock is True and p.inventory == 5 and p.merchant_id == "43483"
    assert p.image_url.startswith("https://cdn.grofers.com/")
    assert page.actual_query == "paneer"
    assert page.next_url.startswith("/v1/layout/search?offset=12")

def test_missing_mrp_equals_price():
    p = by_id(parse_search_page(load("search_paneer_p1.json")), "329500")
    assert (p.price, p.mrp, p.discount_pct, p.sponsored) == (95.0, 95.0, 0, False)

def test_sold_out_card():                     # copy of 329500 card with is_sold_out=True -> in_stock False

def test_filter_page1_keeps_relevant_ads():
    kept = filter_results(parse_search_page(load("search_paneer_p1.json")).products)
    assert len(kept) == 12

def test_filter_page2_drops_filler_ads():
    kept = filter_results(parse_search_page(load("search_paneer_p2.json")).products)
    ids = {p.product_id for p in kept}
    assert len(kept) == 9
    assert not ids & {"495737", "617689", "776437"}

def test_ads_only_is_no_match():               # page2 products with organic ones removed
    ads = [p for p in parse_search_page(load("search_paneer_p2.json")).products if p.sponsored]
    kept = filter_results(ads)
    assert kept == [] and search_status(kept) == "no_match"

def test_all_sold_out_status():
def test_nomatch_fixture():                    # search_nomatch.json -> search_status(filter_results(...)) == "no_match"
def test_product_url():
    assert product_url("329500", "Amul Fresh Malai Paneer") == "https://blinkit.com/prn/amul-fresh-malai-paneer/prid/329500"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_parsers.py -v`
Expected: FAIL (import error).

- [ ] **Step 3: Implement `models.py` and the search functions in `parsers.py`**

Card fields are in spec 7.1. `brand_name` is an object, take `.text`. Sponsored = `tracking.common_attributes.badge == "AD"`. `actual_query` comes from `tracking.le_meta.custom_data.search_actual_keyword`. It can be missing on later pages, so use `None`. Raise `BlinkitError("upstream_changed", ...)` if `response.snippets` is missing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_parsers.py -v`
Expected: all passed.

- [ ] **Step 5: Verify the product URL format live**

Run: `uv run python -c "from blinkit_mcp.client import BlinkitClient as C; print(C().session.get('https://blinkit.com/prn/amul-fresh-malai-paneer/prid/329500').status_code)"` (adapt to the client's attribute name).
Expected: `200`. If not, find the correct format in the page's `<link rel="canonical">` and update `product_url` and its test.

- [ ] **Step 6: Commit**

`git commit -am "feat: parse and filter search results"` (add new files first).

---

### Task 3: Product detail parser

**Files:**
- Modify: `src/blinkit_mcp/models.py`, `src/blinkit_mcp/parsers.py`, `tests/test_parsers.py`

**Interfaces:**
- Consumes: `Product`, `product_url`, `parse_price` (Task 2).
- Produces:
  - `ProductDetail(product: Product, images: list[str], attributes: dict[str, str])`
  - `parse_product(data: dict) -> ProductDetail`. `product.sponsored` is `False`; `product.product_type` is `None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_product_329500():
    d = parse_product(load("product_329500.json"))
    p = d.product
    assert (p.product_id, p.name, p.brand, p.pack_size) == ("329500", "Amul Fresh Malai Paneer", "Amul", "200 g")
    assert (p.price, p.mrp, p.inventory, p.in_stock) == (95.0, 95.0, 5, True)
    assert len(d.images) == 3
    assert d.images[0] == "https://cdn.grofers.com/da/cms-assets/cms/product/98064289-82ca-42ea-a64e-f9465af3c391.jpg"
    assert len(d.attributes) == 26
    assert d.attributes["Protein Per 100 g"] == "20 g"
    assert d.attributes["Energy Per 100 g"] == "312 kcal"
    assert d.attributes["Shelf Life"] == "45 days"
    assert d.attributes["FSSAI License"] == "10012021000071"
    assert "Packaging Type" not in d.attributes      # not_shown_to_customer

def test_product_unstocked():   # behaviour per product_unstocked.json from Task 1:
                                # product data present -> in_stock False; no product data -> BlinkitError "not_found"
def test_product_missing_seo_is_upstream_changed():
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_parsers.py -k product -v`
Expected: FAIL.

- [ ] **Step 3: Implement `parse_product`**

Use the sources in spec 7.2: `seo` for id, name, brand, price, mrp, inventory, images, attributes. Use the `product_atc_strip` snippet for `variant.text`, `is_sold_out`, `merchant_id` (from `meta` or the cart item). If the atc strip is missing, use the `Unit` attribute for the pack size.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_parsers.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

`git commit -am "feat: parse product detail"`

---

### Task 4: Location config, address lookup, serviceability

**Files:**
- Create: `src/blinkit_mcp/config.py`, `src/blinkit_mcp/location.py`, `tests/test_config.py`, `tests/test_location.py`

**Interfaces:**
- Consumes: `BlinkitClient` (Task 1), `parse_search_page`, `filter_results`, `search_status` (Task 2).
- Produces:
  - `config.Location` dataclass: `address: str, lat: float, lon: float, merchant_id: str | None`
  - `config.config_path() -> Path`, `config.load_location() -> Location | None`, `config.save_location(loc: Location) -> None`. Create parent directories when saving.
  - `location.Place` dataclass: `address: str, lat: float, lon: float`
  - `location.resolve_address(client: BlinkitClient, text: str) -> list[Place]`: up to 5 candidates, best first.
  - `location.check_serviceable(client: BlinkitClient, lat: float, lon: float) -> str | None`: returns the store `merchant_id` if serviceable. Raises `BlinkitError("not_serviceable", ...)` if not.

- [ ] **Step 1: Find Blinkit's place-to-coordinates call (discovery, no code)**

Download the blinkit.com home page and its JS bundles with `BlinkitClient` into the scratchpad. Search for `place_id` and `/location/`. Try each candidate endpoint with the `place_id` from `GET /location/autoSuggest?query=koramangala&lat=28.4595&lng=77.0266`.
Result A: an endpoint returns lat/lon for a place id. Use autoSuggest + that endpoint.
Result B: nothing found within about 30 minutes. Use OpenStreetMap Nominatim: `GET https://nominatim.openstreetmap.org/search?q=<text>&format=jsonv2&limit=5&countrycodes=in`, header `User-Agent: blinkit-mcp/0.1 (personal use)`, through `client.get_bytes` or a plain request. Nominatim does not need the Chrome fingerprint.
Write the result in a comment at the top of `location.py`.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_config.py (use tmp_path and monkeypatch BLINKIT_MCP_CONFIG)
def test_load_when_missing_returns_none():
def test_save_then_load_round_trip():          # Location("Koramangala, Bengaluru", 12.9352, 77.6245, "43483")
def test_empty_or_corrupt_file_returns_none(): # "" and "{not json" -> None
def test_env_var_overrides_path():

# tests/test_location.py (fake client)
def test_resolve_address_returns_candidates(): # fake response for the chosen source -> list[Place], lat/lon as float
def test_resolve_address_no_result_is_empty():
def test_serviceable_returns_merchant_id():    # fake search returns search_milk_gurugram.json -> "43483" (or the id in the fixture)
def test_unserviceable_raises():               # fake search returns search_unserviceable.json -> code "not_serviceable"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py tests/test_location.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement `config.py` and `location.py`**

`check_serviceable`: search `"milk"` at the coordinates. If the status is `no_match`, the location is not serviceable. Otherwise return the `merchant_id` of the first organic product. Milk is in every Blinkit store, so `no_match` means no store. (Claude's call, see spec section 11. Task 1 Step 6 checks the assumption.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py tests/test_location.py -v`
Expected: all passed.

- [ ] **Step 6: Commit**

`git commit -am "feat: location config, address lookup, serviceability check"`

---

### Task 5: Image download and resize

**Files:**
- Create: `src/blinkit_mcp/images.py`, `tests/test_images.py`

**Interfaces:**
- Consumes: `BlinkitClient.get_bytes` (Task 1).
- Produces:
  - `MAX_SIDE = 1500`, `MAX_IMAGES = 4`, `ALLOWED_HOST = "cdn.grofers.com"`
  - `validate_url(url: str) -> None`: raises `BlinkitError("bad_input", ...)` unless the scheme is https and the host is `ALLOWED_HOST`.
  - `fetch_image(client, url: str) -> bytes`: validates, downloads, converts to RGB, shrinks so the long side ≤ `MAX_SIDE` (never enlarges), returns JPEG bytes (quality 85).

- [ ] **Step 1: Write the failing tests** (generate test images with Pillow in memory)

```python
def test_rejects_other_hosts():      # "https://evil.example.com/a.jpg" -> bad_input; fake client get_bytes never called
def test_rejects_http():             # "http://cdn.grofers.com/a.jpg" -> bad_input
def test_large_image_is_shrunk():    # 3000x2000 PNG -> JPEG 1500x1000
def test_small_image_unchanged():    # 800x600 -> 800x600
def test_png_with_alpha_converts():  # RGBA PNG -> valid JPEG
def test_not_an_image_is_upstream_changed():
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_images.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `images.py`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_images.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

`git commit -am "feat: image download and resize"`

---

### Task 6: MCP server tools

**Files:**
- Create: `src/blinkit_mcp/server.py`, `tests/test_server.py`, `tests/test_live.py`, `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: FastMCP app `mcp = FastMCP("blinkit")`, `main()` runs stdio. Module-level `get_client()` returns one shared `BlinkitClient`. Tests replace it with a fake.
- Tool functions. Each returns a `dict`. On failure the dict is `{"status": <error code>, "message": str}`.
  - `set_location(address: str | None = None, lat: float | None = None, lon: float | None = None) -> dict`
  - `get_location() -> dict`
  - `search_products(query: str, limit: int = 10, lat: float | None = None, lon: float | None = None) -> dict`
  - `get_product(product_id: str, lat: float | None = None, lon: float | None = None) -> dict`
  - `view_images(product_id: str | None = None, indexes: list[int] | None = None, urls: list[str] | None = None) -> list` (MCP content: per image, one text item `"[<index>] <url>"` and one `mcp.server.fastmcp.Image(data=..., format="jpeg")`. On failure: one text item with the error dict as JSON.)

Behaviour:
- Location for a call: the `lat`/`lon` arguments if both are given, else the saved location, else `{"status": "no_location", "message": "Call set_location first."}`.
- `set_location`: with lat/lon, skip resolving. With an address, if `resolve_address` returns more than one candidate and the first does not clearly match, return `{"status": "bad_input", "candidates": [...]}` and save nothing. Otherwise run `check_serviceable` and save `Location` with `merchant_id`. Return the saved location and `"serviceable": true`. If not serviceable, return `not_serviceable` and save nothing.
  - "Clearly match" is a builder decision. Recommended: one candidate, or the user passes lat/lon from a candidate on the second call.
- `search_products`: `limit` is clamped to 1..30. Fetch pages with `next_url` until there are `limit` kept products, there is no `next_url`, or 3 pages are fetched. Filter over all fetched cards. Output keys: `status`, `query`, `actual_query`, `location` (address, lat, lon), `merchant_id`, `count`, `products` (list of `Product` as dict), and `reason` when `count == 0`, and `warning` when the merchant id is different from the saved one.
- `get_product`: `ProductDetail` as dict, plus `location` and `warning` as above.
- `view_images`: with `product_id`, call `get_product` to get the gallery. `indexes` default `[0, 1, 2, 3]`, limited to the gallery length. An index outside the gallery → `bad_input`. More than `MAX_IMAGES` requested → `bad_input`.

- [ ] **Step 1: Write the failing tests** in `tests/test_server.py`. Use a fake client that serves fixtures, and `BLINKIT_MCP_CONFIG` in `tmp_path`.

```python
def test_search_without_location_is_no_location():
def test_search_uses_saved_location_headers():     # fake records lat/lon of the saved location
def test_search_follows_pages_and_filters():       # p1 then p2, limit=30 -> count == 21, no 495737
def test_search_limit_stops_paging():              # limit=5 -> one request, count == 5
def test_search_empty_has_reason():                # nomatch fixture -> status "no_match", reason present
def test_store_change_adds_warning():              # saved merchant "99999" -> "warning" in result
def test_get_product_returns_attributes():         # attributes["Shelf Life"] == "45 days"
def test_view_images_index_out_of_range():         # indexes=[5] for 3-image gallery -> bad_input, no get_bytes call
def test_view_images_bad_host():                   # urls=["https://evil.example.com/a.jpg"] -> bad_input
def test_view_images_returns_images():             # indexes=[0] -> one text + one Image
def test_set_location_with_coordinates_saves():    # lat/lon + milk fixture -> config file has merchant id
def test_set_location_unserviceable_saves_nothing():
def test_get_location_not_set_then_set():
def test_blinkit_error_becomes_status_dict():      # fake raises BlinkitError("blocked") -> {"status": "blocked", ...}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_server.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `server.py`**

Tool docstrings are what the assistant reads. In each one, say what the tool returns and when to use it. For example, in `get_product`: "Check `attributes` for nutrition per 100 g before you call `view_images`."

- [ ] **Step 4: Run all tests**

Run: `uv run pytest -v`
Expected: all passed. `test_live.py` is skipped.

- [ ] **Step 5: Write `tests/test_live.py`** (skipped unless `BLINKIT_LIVE=1`): set location 28.4595, 77.0266 → `search_products("paneer")` has status `found` → `get_product` of the first result has ≥ 1 image → `view_images(product_id, [0])` returns an image.

Run: `BLINKIT_LIVE=1 uv run pytest tests/test_live.py -v`
Expected: 1 passed.

- [ ] **Step 6: Check the server in an MCP client**

Run: `uv run mcp dev src/blinkit_mcp/server.py` (MCP Inspector), or add it to Claude Code with `claude mcp add blinkit -- uv --directory <repo> run blinkit-mcp`. Call `set_location` with the user's address, then `search_products("kasuri methi")`.
Expected: real results for the user's address.

- [ ] **Step 7: Write `README.md`**: install, register in Claude Code and Claude Desktop, the five tools, the config path, and the warning that Blinkit's private API can change.

- [ ] **Step 8: Commit**

`git add -A && git commit -m "feat: MCP server tools"`
