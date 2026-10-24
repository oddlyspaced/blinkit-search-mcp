import dataclasses
import json
from pathlib import Path

import pytest

from blinkit_mcp.errors import BlinkitError
from blinkit_mcp.parsers import (
    filter_results,
    parse_price,
    parse_search_page,
    product_url,
    search_status,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def by_id(page, product_id):
    return next(p for p in page.products if p.product_id == product_id)


def test_parse_price():
    assert parse_price("₹95") == 95.0
    assert parse_price("₹1,299") == 1299.0
    assert parse_price("₹12.50") == 12.5
    assert parse_price(None) is None
    assert parse_price("") is None


def test_search_page1_fields():
    page = parse_search_page(load("search_paneer_p1.json"))
    assert len(page.products) == 12
    p = page.products[0]
    assert (p.product_id, p.name, p.brand, p.pack_size) == (
        "686510",
        "Pride of Cows Low Fat High Protein Paneer",
        "Pride of Cows",
        "200 g",
    )
    assert (p.price, p.mrp, p.discount_pct) == (219.0, 235.0, 6)
    assert p.sponsored is True and p.product_type == "Paneer"
    assert p.matches_query is False
    assert p.in_stock is True and p.inventory == 5 and p.merchant_id == "43483"
    assert p.image_url.startswith("https://cdn.grofers.com/")
    assert p.url == "https://blinkit.com/prn/pride-of-cows-low-fat-high-protein-paneer/prid/686510"
    assert page.actual_query == "paneer"
    assert page.next_url.startswith("/v1/layout/search?offset=12")


def test_organic_match_flag():
    p = by_id(parse_search_page(load("search_paneer_p1.json")), "329500")
    assert p.sponsored is False and p.matches_query is True


def test_missing_mrp_equals_price():
    p = by_id(parse_search_page(load("search_paneer_p1.json")), "329500")
    assert (p.price, p.mrp, p.discount_pct) == (95.0, 95.0, 0)


def test_sold_out_card():
    data = load("search_paneer_p1.json")
    card = next(s for s in data["response"]["snippets"] if s["data"].get("product_id") == "329500")
    card["data"]["is_sold_out"] = True
    card["data"]["inventory"] = 0
    p = by_id(parse_search_page(data), "329500")
    assert p.in_stock is False and p.inventory == 0


def test_missing_snippets_is_upstream_changed():
    with pytest.raises(BlinkitError) as e:
        parse_search_page({"is_success": True, "response": {}})
    assert e.value.code == "upstream_changed"


def test_filter_page1_keeps_relevant_ads():
    kept = filter_results(parse_search_page(load("search_paneer_p1.json")).products)
    assert len(kept) == 12


def test_filter_page2_drops_filler_ads():
    kept = filter_results(parse_search_page(load("search_paneer_p2.json")).products)
    ids = {p.product_id for p in kept}
    assert len(kept) == 9
    assert not ids & {"495737", "617689", "776437"}


def test_ads_only_is_no_match():
    ads = [p for p in parse_search_page(load("search_paneer_p2.json")).products if p.sponsored]
    kept = filter_results(ads)
    assert kept == [] and search_status(kept) == "no_match"


def test_nomatch_fixture_filler_is_dropped():
    page = parse_search_page(load("search_nomatch.json"))
    assert len(page.products) == 12
    kept = filter_results(page.products)
    assert kept == [] and search_status(kept) == "no_match"


def test_all_sold_out_status():
    kept = filter_results(parse_search_page(load("search_paneer_p1.json")).products)
    sold_out = [dataclasses.replace(p, in_stock=False) for p in kept]
    assert search_status(sold_out) == "all_sold_out"


def test_found_status():
    kept = filter_results(parse_search_page(load("search_paneer_p1.json")).products)
    assert search_status(kept) == "found"


def test_product_url():
    assert product_url("329500", "Amul Fresh Malai Paneer") == "https://blinkit.com/prn/amul-fresh-malai-paneer/prid/329500"
    assert product_url("1", "Let's Try Jowar (Millet) Cookies") == "https://blinkit.com/prn/let-s-try-jowar-millet-cookies/prid/1"
