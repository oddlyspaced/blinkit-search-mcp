"""Convert Blinkit JSON into models.

This is the only module that knows Blinkit's response formats. See section 7
of docs/superpowers/specs/2026-10-24-blinkit-mcp-design.md.
"""

import functools
import math
import re

from .errors import NOT_FOUND, UPSTREAM_CHANGED, BlinkitError
from .models import Place, Product, ProductDetail, SearchPage, Suggestion

PRODUCT_CARD = "product_card_snippet_type_2"
ATC_STRIP = "product_atc_strip"
SHOWN = "shown_to_customer"
FOUND, ALL_SOLD_OUT, NO_MATCH = "found", "all_sold_out", "no_match"


def parse_price(text: str | None) -> float | None:
    if not text:
        return None
    digits = re.sub(r"[^\d.]", "", text)
    return float(digits) if digits else None


def product_url(product_id: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"https://blinkit.com/prn/{slug}/prid/{product_id}"


def discount_pct(price: float | None, mrp: float | None) -> int:
    if not price or not mrp or mrp <= price:
        return 0
    return math.floor((mrp - price) / mrp * 100)


def _text(obj) -> str | None:
    if isinstance(obj, dict):
        return obj.get("text") or None
    return obj or None


def _shape_errors(fn):
    """Report missing or wrongly typed fields as upstream_changed."""

    @functools.wraps(fn)
    def wrapper(data):
        try:
            return fn(data)
        except (KeyError, TypeError, AttributeError, IndexError, ValueError) as exc:
            raise BlinkitError(UPSTREAM_CHANGED, f"Blinkit response format changed ({type(exc).__name__}: {exc})")

    return wrapper


def _is_query_match(reason: str) -> bool:
    """Blinkit's match reason. Popular-item filler has only qtp_products* tokens.

    Real matches can also carry qtp_products_injected, so only an all-filler
    reason counts as no match. An unknown reason counts as a match.
    """
    tokens = [t for t in reason.split(",") if t]
    return not tokens or not all(t.startswith("qtp_products") for t in tokens)


def _response(data: dict, key: str):
    try:
        return data["response"][key]
    except (KeyError, TypeError):
        raise BlinkitError(UPSTREAM_CHANGED, f"Blinkit response has no response.{key}")


def parse_card(snippet: dict) -> Product:
    d = snippet["data"]
    attrs = (snippet.get("tracking") or {}).get("common_attributes") or {}
    product_id = str(d["product_id"])
    name = _text(d.get("name")) or _text(d.get("display_name")) or ""
    price = parse_price(_text(d.get("normal_price")))
    mrp = parse_price(_text(d.get("mrp"))) or price
    sponsored = attrs.get("badge") == "AD"
    inventory = d.get("inventory")
    return Product(
        product_id=product_id,
        name=name,
        brand=_text(d.get("brand_name")),
        pack_size=_text(d.get("variant")),
        price=price,
        mrp=mrp,
        discount_pct=discount_pct(price, mrp),
        in_stock=not d.get("is_sold_out", False) and inventory != 0,
        inventory=inventory,
        image_url=(d.get("image") or {}).get("url"),
        url=product_url(product_id, name),
        product_type=attrs.get("ptype") or None,
        sponsored=sponsored,
        matches_query=not sponsored and _is_query_match(attrs.get("reason") or ""),
        merchant_id=str(d["merchant_id"]) if d.get("merchant_id") is not None else None,
    )


@_shape_errors
def parse_search_page(data: dict) -> SearchPage:
    snippets = _response(data, "snippets")
    custom = ((data["response"].get("tracking") or {}).get("le_meta") or {}).get("custom_data") or {}
    return SearchPage(
        products=[parse_card(s) for s in snippets if s.get("widget_type") == PRODUCT_CARD],
        actual_query=custom.get("search_actual_keyword") or None,
        next_url=(data["response"].get("pagination") or {}).get("next_url") or None,
    )


def filter_results(products: list[Product]) -> list[Product]:
    """Keep query matches, and ads of the same product type as a match."""
    matched_types = {p.product_type.lower() for p in products if p.matches_query and p.product_type}
    return [
        p
        for p in products
        if p.matches_query or (p.sponsored and p.product_type and p.product_type.lower() in matched_types)
    ]


def search_status(kept: list[Product]) -> str:
    if not any(p.matches_query for p in kept):
        return NO_MATCH
    if not any(p.in_stock for p in kept):
        return ALL_SOLD_OUT
    return FOUND


def _atc_merchant_id(atc: dict) -> str | None:
    meta = atc.get("meta") or {}
    if meta.get("merchant_id") is not None:
        return str(meta["merchant_id"])
    for action in (atc.get("rfc_actions_v2") or {}).get("default") or []:
        item = ((action or {}).get("remove_from_cart") or {}).get("cart_item") or {}
        if item.get("merchant_id") is not None:
            return str(item["merchant_id"])
    return None


@_shape_errors
def parse_product(data: dict) -> ProductDetail:
    custom = (((data.get("response") or {}).get("tracking") or {}).get("le_meta") or {}).get("custom_data") or {}
    if "seo" in custom and custom["seo"] is None:
        # Unknown product id: is_success=false, snippets=null, seo=null.
        raise BlinkitError(NOT_FOUND, "Blinkit has no product with this id")
    snippets = _response(data, "snippets") or []
    seo = custom.get("seo")
    if not isinstance(seo, dict) or "id" not in seo:
        raise BlinkitError(UPSTREAM_CHANGED, "Blinkit product response has no seo block")
    attributes = {a["name"]: str(a["value"]) for a in seo.get("attributes") or [] if a.get("type") == SHOWN}
    atc = next((s["data"] for s in snippets if s.get("widget_type") == ATC_STRIP), {})
    product_id = str(seo["id"])
    name = seo.get("product_name") or ""
    # Blinkit reports price 0 when no store near the location stocks the item.
    price = float(seo["price"]) if seo.get("price") else None
    mrp = float(seo["mrp"]) if seo.get("mrp") else price
    inventory = seo.get("inventory", atc.get("inventory"))
    images = list(seo.get("images") or [])
    product = Product(
        product_id=product_id,
        name=name,
        brand=seo.get("brand") or None,
        pack_size=_text(atc.get("variant")) or attributes.get("Unit"),
        price=price,
        mrp=mrp,
        discount_pct=discount_pct(price, mrp),
        in_stock=not atc.get("is_sold_out", False) and bool(inventory),
        inventory=inventory,
        image_url=images[0] if images else None,
        url=product_url(product_id, name),
        product_type=None,
        sponsored=False,
        matches_query=False,
        merchant_id=_atc_merchant_id(atc),
    )
    return ProductDetail(product=product, images=images, attributes=attributes)


def parse_suggestions(data: dict) -> list[Suggestion]:
    """Parse GET /location/autoSuggest. No match gives an empty `ui_data`."""
    out = []
    for s in (data.get("ui_data") or {}).get("suggestions") or []:
        place_id = (s.get("meta") or {}).get("place_id")
        if place_id:
            out.append(Suggestion(title=_text(s.get("title")) or "", subtitle=_text(s.get("subtitle")) or "", place_id=place_id))
    return out


def parse_place_info(data: dict) -> Place:
    """Parse GET /location/info?place_id=... (lat/lng queries return no data)."""
    coord = data.get("coordinate") or {}
    lat, lon = coord.get("lat"), coord.get("lon")
    if not lat or not lon:
        raise BlinkitError(NOT_FOUND, "Blinkit returned no coordinates for this place")
    address = (data.get("display_address") or {}).get("address_line") or ""
    return Place(address=address, lat=float(lat), lon=float(lon))
