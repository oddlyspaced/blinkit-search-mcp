"""Convert Blinkit JSON into models.

This is the only module that knows Blinkit's response formats. See section 7
of docs/superpowers/specs/2026-10-24-blinkit-mcp-design.md.
"""

import math
import re

from .errors import UPSTREAM_CHANGED, BlinkitError
from .models import Product, ProductDetail, SearchPage

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


def _response(data: dict, key: str):
    try:
        return data["response"][key]
    except (KeyError, TypeError):
        raise BlinkitError(UPSTREAM_CHANGED, f"Blinkit response has no response.{key}")


def parse_card(snippet: dict) -> Product:
    d = snippet["data"]
    attrs = snippet.get("tracking", {}).get("common_attributes", {})
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
        matches_query=not sponsored and "match" in (attrs.get("reason") or ""),
        merchant_id=str(d["merchant_id"]) if d.get("merchant_id") is not None else None,
    )


def parse_search_page(data: dict) -> SearchPage:
    snippets = _response(data, "snippets")
    custom = data["response"].get("tracking", {}).get("le_meta", {}).get("custom_data", {})
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


def parse_product(data: dict) -> ProductDetail:
    snippets = _response(data, "snippets")
    custom = data["response"].get("tracking", {}).get("le_meta", {}).get("custom_data", {})
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
