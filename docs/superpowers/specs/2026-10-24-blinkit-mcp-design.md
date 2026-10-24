# Blinkit MCP Server — Design

Date: 2026-10-24
Status: Draft, waiting for approval

## 1. Intent

The user plans a dish and wants an AI assistant to find the raw ingredients on
Blinkit (blinkit.com, an Indian quick-commerce grocery service). For each
ingredient, the assistant must find matching products and report price, pack
size, product information, images, and availability at the user's address.

This server is the data layer. It exposes Blinkit browse data as MCP tools. The
assistant does the reasoning: it converts a dish into ingredients, it selects
products, and it reads product images (for example, a nutrition table on a
back-of-pack photo).

## 2. Goals

- Set a delivery location once and keep it across sessions.
- Search products at that location.
- Get full product detail: all images, description, attributes.
- Show product images to the assistant so it can read them.
- Report availability correctly: in stock, sold out, or not sold at this
  location.

## 3. Non-goals

- Login, cart, checkout, orders. The server is read-only.
- Recipe knowledge. The assistant converts dishes to ingredients.
- Image analysis inside the server (no OCR). The assistant reads the images.
- Price history, tracking, or background polling.
- Multi-user or hosted deployment.

## 4. Anti-goals (failure even if it "works")

- Silent wrong location. Results from a default city when the user's location
  is not set, or results from a different store, without saying so.
- Empty results with no reason. Every empty result must say why (no match,
  not serviceable, blocked, error).
- Unrelated products shown as matches. Blinkit pads search pages with
  recommendations (for example, chilli oil in a "paneer" search). These must
  not be returned as search matches.
- Aggressive traffic that gets the user's IP blocked.

## 5. Constraints

- Blinkit has no public API. The server uses the private endpoints of the
  blinkit.com web app. These can change or be blocked without notice.
- Plain HTTP clients (curl, `requests`, `httpx`) get HTTP 403. The block is on
  the TLS fingerprint. A client with a Chrome TLS fingerprint works. Verified:
  Python `curl_cffi` with `impersonate="chrome"`.
- Personal, local use only. Transport is stdio. Target clients are Claude Code
  and Claude Desktop. Both accept MCP image content.

## 6. Decisions

Decided by the user:

- Browse only. No cart.
- No batch search tool. One search per item.
- One fixed address, used for all sessions.
- Image URLs in normal results are sufficient. The assistant must also be able
  to view images on request to extract information such as nutrition values.

Decided by Claude (the user can change these):

- Language: Python. HTTP client: `curl_cffi`. MCP SDK: official `mcp` Python
  package (FastMCP). Packaging: `uv`, runnable with `uvx` or `uv run`.
- No browser automation (Playwright and similar). Use it only if the HTTP
  approach stops working.
- Tool set as in section 8, including the `view_images` tool.

## 7. Recon findings (2026-10-24)

All calls go to `https://blinkit.com`. Common headers:

- `lat`, `lon`: delivery coordinates. These select the store.
- `app_client: consumer_web`
- `content-type: application/json`
- `origin: https://blinkit.com`

Do a `GET /` first in the session to collect cookies. (The tests did this.
Not verified whether it is required.)

### 7.1 Search — verified

`POST /v1/layout/search?q=<query>&search_type=type_to_search`, body `{}`.

- Response: `response.snippets[]`. Product cards have
  `widget_type == "product_card_snippet_type_2"`.
- Product card fields (`snippet.data`): `product_id`, `name.text`,
  `brand_name`, `variant.text` (pack size, for example "200 g"),
  `normal_price.text` ("₹95"), `mrp.text`, `offer_tag`, `image.url`,
  `inventory` (int), `is_sold_out` (bool), `product_state` ("available"),
  `merchant_id`, `eta_tag`, `rating`, `group_id`.
- Store id is also in `click_action.blinkit_deeplink.url`
  (`grofers://pdp?product_id=…&merchant_id=43483`).
- Pagination: `response.pagination.next_url` is a relative URL with
  `offset`, `limit=12`, and other state. First page had 12 products.
- Organic results and sponsored ads are mixed on every page. Fields in
  the card's `tracking.common_attributes`:
  - `badge`: `"AD"` for ads, empty for organic results.
  - `ads_campaign_id`: present only for ads.
  - `reason`: the match reason for organic results (for example
    `keyterm|match|paneer,text_match,within_category`). Empty for ads.
  - `ptype`: product type (for example "Paneer", "High Protein Paneer",
    "Chilli Oil").
- Ads can be relevant or not. "paneer" page 1 had 3 ads, all paneer
  (ids 686510, 639120, 481292). Page 2 had 3 ads that were filler:
  495737 "MasterChow Sichuan Chilli Oil" (ptype "Chilli Oil"), 617689
  coconut water, 776437 cookies. The other 9 items on page 2 were organic
  paneer results.
- The deeplink parameter `npr_flag=PRODUCT_RECOMMENDATION` appears on
  almost all cards, organic paneer included. It does NOT mark unrelated
  items. Do not use it.
- The desert search (section 7.3) also returned ad 495737 first.
- The header snippet says `Showing results for "<query>"`. Blinkit can
  change the query (spell correction). Report the actual query used
  (`tracking.le_meta.custom_data.search_actual_keyword`).

### 7.2 Product detail — verified

`POST /v1/layout/product/<product_id>`, body `{}`.

- Response is a layout of mixed snippets (`horizontal_list`,
  `carousal_list_vr`, `product_atc_strip`, and others).
- Primary source: `response.tracking.le_meta.custom_data.seo`. Fields:
  `id`, `product_name`, `brand`, `price` (number), `mrp` (number),
  `inventory` (int), `images` (list of URLs, main product gallery only),
  `categories` (ids only, names empty), `attributes` (list).
  For 329500: name "Amul Fresh Malai Paneer", brand "Amul", price 95,
  mrp 95, inventory 5, 3 images.
- The response also has about 24 image URLs in other snippets. Those are
  similar products and "people also bought". Ignore them.
- Pack size and stock: snippet `product_atc_strip` → `variant.text`
  ("200 g"), `is_sold_out`, `product_state`. The `seo` attribute "Unit"
  also gives "200 g".
- Attributes are objects with `name`, `value`, `type`. Keep
  `type == "shown_to_customer"` (26 of 40 for 329500). These include
  Description, Key Features, Ingredients, Shelf Life ("45 days"),
  Manufacturer's Name and Address, Country of Origin ("India"),
  FSSAI License ("10012021000071"), Diet Preference, and nutrition per
  100 g: "Protein Per 100 g" ("20 g"), "Energy Per 100 g" ("312 kcal"),
  carbohydrates, fats, sodium, calcium, cholesterol, added sugar.
  Not verified: how many other products have the nutrition attributes.

### 7.3 Location — partly verified

- `GET /location/autoSuggest?query=<text>&lat=..&lng=..` returned
  suggestions with title, subtitle, and `meta.place_id` (Google place id),
  `meta.session_token`. One later call without `lat`/`lng` returned a
  response without `ui_data` (not investigated).
- Not found: the endpoint that converts `place_id` to lat/lon.
  `/location/latLong`, `/location/placeDetails`, `/location/place` were
  not confirmed.
- `GET /location/info?lat=..&lng=..` returned `is_serviceable: false` for
  both Koramangala, Bengaluru (should be serviceable) and the Thar desert.
  Treat it as unreliable until the correct call is known.
- Search at a desert location (26.9, 70.9) still returned products (store
  48298). The first item was an ad (see 7.1). The other items were not
  inspected.

## 8. Tools

All tools use the saved location unless the call gives `lat`/`lon`. If no
location is saved and none is given, the tool returns an error that tells
the assistant to call `set_location`.

### 8.1 `set_location`

- Input: `address` (text) or `lat` + `lon`.
- Resolves the address to coordinates, checks serviceability, saves the
  result to the config file.
- Output: resolved address, lat/lon, serviceable yes/no, store id if known.
- If the address matches more than one place, return the candidates and
  save nothing.

### 8.2 `get_location`

- Output: the saved location, or "not set".

### 8.3 `search_products`

- Input: `query`, `limit` (default 10, maximum 30).
- Output per product: `product_id`, name, brand, pack size, price (number,
  INR), MRP (number), discount percent, `in_stock` (bool), `inventory`,
  main image URL, product URL on blinkit.com.
- Output per call: query as sent, actual query used by Blinkit, location,
  store id, count, and a `reason` field when the list is empty.
- Each product also has `sponsored` (bool) and `product_type` (the
  `ptype` value).
- Filter rule (Claude's call, based on section 7.1):
  1. Keep all organic results.
  2. Keep an ad only if its `product_type` equals, ignoring case, the
     `product_type` of at least one organic result on the pages fetched.
  3. Drop all other ads.
  4. If no organic result exists, the status is `no_match`, even if ads
     exist.
- Do not filter organic results by name. Blinkit's own match decides
  (for example, "paneer" matched items tagged "cottage cheese").
- Store check: report the store id on every call. `set_location` saves the
  store id it sees. If a later call returns a different store id, include
  a `warning` field in the output. Do not fail the call. (Claude's call.
  The recon did not show whether one location always maps to one store.)
- Output per call also has a `status`: `found`, `all_sold_out`,
  `no_match`, or an error from section 9.
- `no_match` covers "not sold at this location". Search only sees the
  catalog of the local store, so the server cannot tell "Blinkit never
  sells this" apart from "this store does not sell it". (Claude's call.)
- One call searches one item. The assistant calls this tool once per
  ingredient. (User's decision: no batch search tool.)

### 8.4 `get_product`

- Input: `product_id`.
- Output: all fields from 8.3, plus all gallery image URLs (in order),
  and all customer-visible attributes as name → value pairs (description,
  key features, ingredients, shelf life, manufacturer, origin, FSSAI, and
  any nutrition text).
- If the local store does not stock the product, return the product data
  that Blinkit gives with `in_stock: false` and a note. If Blinkit returns
  no product data, return `not_found`. The builder must capture what
  Blinkit actually returns in this case before writing the parser.

### 8.5 `view_images`

- Input: `product_id` and optional `indexes` (positions in the gallery),
  or a list of image URLs.
- Downloads the images and returns them as MCP image content.
- Resize so that the long side is at most about 1500 px (enough to read
  label text). Maximum 4 images per call.
- Accept only URLs on Blinkit's image CDN (`cdn.grofers.com`).
- Each image comes with its URL and gallery position, so the assistant
  can ask for more.

## 9. Behaviour requirements

- **Location persistence.** Save the location in a JSON file in the user
  config directory (for example `~/.config/blinkit-mcp/config.json`).
  Allow an environment variable to override the path.
- **Rate limit.** At most about 1 request per second. No retries in a
  tight loop. At most one retry after a block, with a delay.
- **Errors.** Use distinct, clear errors: `blocked` (403 or bot page),
  `not_serviceable`, `not_found`, `upstream_changed` (expected fields
  missing), `network`.
- **Shape isolation.** Put all knowledge of Blinkit's response formats in
  one parser module, so that a format change needs a fix in one place.
- **Prices** are numbers in INR, parsed from strings like "₹1,299".
- **Caching.** Optional, in memory only: product detail for a few minutes.
  No disk cache.

## 10. Testing

- The repo has no saved responses yet. The first build step is to capture
  real responses as fixtures: search page 1, search page 2, a
  no-match search, an unserviceable location, product detail, and a product
  not stocked at the local store.
- Unit tests for the parsers, using saved real responses as fixtures
  (search page 1, search page 2 with recommendations, product detail).
- One live smoke test, not run by default (for example behind an env
  flag): set a known serviceable location, search "paneer", get one
  product, view one image.

## 11. Left to the builder

- How to resolve address to lat/lon. Find Blinkit's own endpoint (inspect
  the web app's network calls). If none is usable, use a free geocoder
  (for example OpenStreetMap Nominatim, with its usage policy). Lat/lon
  input must work in all cases.
- How to determine serviceability reliably (for example: a working
  `/location/info` call, or an empty or recommendation-only search).
- How much of the pagination to follow to reach `limit`.
- Project layout, module names, and dependency versions.
