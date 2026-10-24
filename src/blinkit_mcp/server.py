"""MCP server: read-only Blinkit browsing tools over stdio."""

import functools
import json
import re
import threading
from dataclasses import asdict

from mcp.server.mcpserver import Image, MCPServer

from .client import BlinkitClient
from .config import Location, load_location, save_location
from .errors import BAD_INPUT, NO_LOCATION, NOT_FOUND, BlinkitError
from .images import MAX_IMAGES, fetch_image, validate_url
from .location import DEFAULT_BIAS, check_serviceable, place_location, suggest_places
from .models import Product
from .parsers import NO_MATCH, filter_results, parse_product, parse_search_page, search_status

MAX_LIMIT = 30
MAX_PAGES = 3
DETAIL_ONLY_FIELDS = ("product_type", "sponsored", "matches_query")  # meaningless on a product page

mcp = MCPServer(
    "blinkit",
    instructions=(
        "Read-only access to Blinkit (Indian quick-commerce grocery). Prices, stock and "
        "catalog depend on the delivery location: call get_location first, and "
        "set_location if none is saved. Search one ingredient per search_products call."
    ),
)

_client: BlinkitClient | None = None
_client_lock = threading.Lock()


def get_client():
    global _client
    with _client_lock:
        if _client is None:
            _client = BlinkitClient()
        return _client


def _fail(err: BlinkitError) -> dict:
    return {"status": err.code, "message": err.message}


def _safe(fn):
    """Return BlinkitError as a status dict instead of a tool error."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except BlinkitError as err:
            return _fail(err)

    return wrapper


def _location(lat: float | None, lon: float | None) -> tuple[Location, bool]:
    """Return (location, is_saved). Explicit coordinates win over the saved location."""
    if lat is not None and lon is not None:
        return Location(f"{lat}, {lon}", lat, lon, None), False
    saved = load_location()
    if saved is None:
        raise BlinkitError(NO_LOCATION, "No delivery location is saved. Call set_location first.")
    return saved, True


def _location_info(loc: Location, merchant_id: str | None, is_saved: bool) -> dict:
    out = {
        "location": {"address": loc.address, "lat": loc.lat, "lon": loc.lon},
        "merchant_id": merchant_id,
    }
    if is_saved and loc.merchant_id and merchant_id and merchant_id != loc.merchant_id:
        out["warning"] = (
            f"Blinkit served this from store {merchant_id}, not store {loc.merchant_id} seen when "
            "the location was saved. Prices and stock can differ."
        )
    return out


def _product_dict(p: Product) -> dict:
    return asdict(p)


@mcp.tool()
@_safe
def set_location(
    address: str | None = None,
    place_id: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> dict:
    """Save the delivery location used by all other tools (kept across sessions).

    Give ONE of:
    - address: free text, e.g. "HSR Layout Sector 2, Bengaluru". Returns
      status "choose_place" with candidates and saves nothing. Then call again
      with the place_id of the right candidate.
    - place_id: from a candidate. Saves that place.
    - lat and lon: saves these coordinates directly.
    Saving checks that Blinkit delivers there (status "not_serviceable" if not).
    """
    client = get_client()
    if lat is not None and lon is not None:
        address_text, plat, plon = f"{lat}, {lon}", lat, lon
    elif place_id:
        place = place_location(client, place_id)
        address_text, plat, plon = place.address, place.lat, place.lon
    elif address and address.strip():
        saved = load_location()
        bias = (saved.lat, saved.lon) if saved else DEFAULT_BIAS
        candidates = suggest_places(client, address.strip(), bias)
        if not candidates:
            raise BlinkitError(NOT_FOUND, f"Blinkit found no place for {address!r}. Try a different address.")
        return {
            "status": "choose_place",
            "message": "Nothing saved yet. Call set_location again with the place_id of the right candidate.",
            "candidates": [asdict(c) for c in candidates],
        }
    else:
        raise BlinkitError(BAD_INPUT, "Give an address, a place_id, or both lat and lon.")
    merchant_id = check_serviceable(client, plat, plon)
    loc = Location(address_text, plat, plon, merchant_id)
    save_location(loc)
    return {"status": "ok", "serviceable": True, **_location_info(loc, merchant_id, False)}


@mcp.tool()
@_safe
def get_location() -> dict:
    """Return the saved delivery location, or status "no_location"."""
    loc, _ = _location(None, None)
    return {"status": "ok", "location": asdict(loc)}


@mcp.tool()
@_safe
def search_products(query: str, limit: int = 10, lat: float | None = None, lon: float | None = None) -> dict:
    """Search Blinkit for ONE item at the saved location (or at lat/lon if given).

    Returns status "found", "all_sold_out" (matches exist, none in stock) or
    "no_match" (this store does not sell it), plus products with price and MRP
    in INR, pack size, in_stock, image_url and product_id. Unrelated sponsored
    items are removed; sponsored=true marks a relevant ad.
    """
    if not query or not query.strip():
        raise BlinkitError(BAD_INPUT, "query is empty")
    query = query.strip()
    limit = max(1, min(MAX_LIMIT, limit))
    loc, is_saved = _location(lat, lon)
    client = get_client()

    cards: dict[str, Product] = {}
    actual_query = None
    next_url = None
    for page_no in range(MAX_PAGES):
        page = parse_search_page(client.search(query, loc.lat, loc.lon, next_url=next_url))
        if page_no == 0:
            actual_query = page.actual_query
        for p in page.products:
            cards.setdefault(p.product_id, p)
        kept = filter_results(list(cards.values()))
        next_url = page.next_url
        if len(kept) >= limit or not next_url:
            break

    status = search_status(kept)
    # Matches first, then relevant ads, so ads never push out real results.
    kept = sorted(kept, key=lambda p: not p.matches_query)[:limit] if status != NO_MATCH else []
    merchant_id = next((p.merchant_id for p in cards.values() if p.merchant_id), None)
    out = {
        "status": status,
        "query": query,
        "actual_query": actual_query,
        **_location_info(loc, merchant_id, is_saved),
        "count": len(kept),
        "products": [_product_dict(p) for p in kept],
    }
    if not kept:
        out["reason"] = f"Blinkit has no product matching {query!r} at this location's store."
    return out


@mcp.tool()
@_safe
def get_product(product_id: str, lat: float | None = None, lon: float | None = None) -> dict:
    """Full product details: all gallery image URLs and every customer-visible
    attribute (description, ingredients, shelf life, manufacturer, FSSAI, and
    often nutrition per 100 g). Check attributes for nutrition before you call
    view_images."""
    if not re.fullmatch(r"\d+", product_id or ""):
        raise BlinkitError(BAD_INPUT, f"product_id must be digits, got {product_id!r}")
    loc, is_saved = _location(lat, lon)
    detail = parse_product(get_client().product(product_id, loc.lat, loc.lon))
    product = {k: v for k, v in _product_dict(detail.product).items() if k not in DETAIL_ONLY_FIELDS}
    out = {
        "status": "ok",
        **_location_info(loc, detail.product.merchant_id, is_saved),
        "product": product,
        "images": detail.images,
        "attributes": detail.attributes,
    }
    if not detail.product.in_stock:
        out["note"] = (
            "Not in stock at this location's store."
            + (" Blinkit gives no price for it here." if detail.product.price is None else "")
        )
    return out


@mcp.tool(structured_output=False)
def view_images(
    product_id: str | None = None,
    indexes: list[int] | None = None,
    urls: list[str] | None = None,
) -> list:
    """Show product images so you can read them (e.g. a nutrition table or
    ingredients on the back of the pack). Give product_id (optionally with
    gallery indexes, default the first 4) OR up to 4 image urls from Blinkit's
    CDN. Each image comes after a "[index] url" line."""
    try:
        targets = _image_targets(product_id, indexes, urls)
        client = get_client()
        out: list = []
        for index, url in targets:
            out.append(f"[{index}] {url}")
            out.append(Image(data=fetch_image(client, url), format="jpeg"))
        return out
    except BlinkitError as err:
        return [json.dumps(_fail(err))]


def _image_targets(product_id, indexes, urls) -> list[tuple[int, str]]:
    if bool(product_id) == bool(urls):
        raise BlinkitError(BAD_INPUT, "Give either product_id or urls.")
    if urls:
        if len(urls) > MAX_IMAGES:
            raise BlinkitError(BAD_INPUT, f"At most {MAX_IMAGES} images per call.")
        for url in urls:
            validate_url(url)
        return list(enumerate(urls))
    gallery = get_product.__wrapped__(product_id)["images"]
    if indexes is None:
        indexes = list(range(min(MAX_IMAGES, len(gallery))))
    if len(indexes) > MAX_IMAGES:
        raise BlinkitError(BAD_INPUT, f"At most {MAX_IMAGES} images per call.")
    bad = [i for i in indexes if not 0 <= i < len(gallery)]
    if bad:
        raise BlinkitError(BAD_INPUT, f"Gallery has {len(gallery)} images (indexes 0-{len(gallery) - 1}); got {bad}.")
    return [(i, gallery[i]) for i in indexes]


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
