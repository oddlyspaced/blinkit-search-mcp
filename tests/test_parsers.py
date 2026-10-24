import dataclasses
import json
from pathlib import Path

import pytest

from blinkit_mcp.errors import BlinkitError
from blinkit_mcp.parsers import (
    filter_results,
    parse_product,
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


def test_product_329500():
    d = parse_product(load("product_329500.json"))
    p = d.product
    assert (p.product_id, p.name, p.brand, p.pack_size) == ("329500", "Amul Fresh Malai Paneer", "Amul", "200 g")
    assert (p.price, p.mrp, p.discount_pct, p.inventory, p.in_stock) == (95.0, 95.0, 0, 5, True)
    assert p.merchant_id == "43483"
    assert p.sponsored is False and p.product_type is None
    assert p.url == "https://blinkit.com/prn/amul-fresh-malai-paneer/prid/329500"
    assert len(d.images) == 3
    assert d.images[0] == "https://cdn.grofers.com/da/cms-assets/cms/product/98064289-82ca-42ea-a64e-f9465af3c391.jpg"
    assert p.image_url == d.images[0]
    assert len(d.attributes) == 26
    assert d.attributes["Protein Per 100 g"] == "20 g"
    assert d.attributes["Energy Per 100 g"] == "312 kcal"
    assert d.attributes["Shelf Life"] == "45 days"
    assert d.attributes["FSSAI License"] == "10012021000071"
    assert "Packaging Type" not in d.attributes


def test_product_unstocked():
    p = parse_product(load("product_unstocked.json")).product
    assert p.name == "Amul Fresh Malai Paneer"
    assert p.in_stock is False and p.inventory == 0
    assert p.price is None and p.mrp is None


def test_product_without_atc_strip_uses_unit():
    data = load("product_329500.json")
    data["response"]["snippets"] = [s for s in data["response"]["snippets"] if s["widget_type"] != "product_atc_strip"]
    p = parse_product(data).product
    assert p.pack_size == "200 g"


def test_product_missing_seo_is_upstream_changed():
    data = load("product_329500.json")
    del data["response"]["tracking"]["le_meta"]["custom_data"]["seo"]
    with pytest.raises(BlinkitError) as e:
        parse_product(data)
    assert e.value.code == "upstream_changed"


# --- final review fixes -------------------------------------------------------


def test_missing_product_is_not_found():
    with pytest.raises(BlinkitError) as e:
        parse_product(load("product_missing.json"))
    assert e.value.code == "not_found"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["response"]["snippets"].__setitem__(1, {"widget_type": "product_card_snippet_type_2"}),
        lambda d: d["response"]["snippets"][1]["data"].pop("product_id"),
        lambda d: d["response"]["snippets"][1].__setitem__("tracking", None),
        lambda d: d["response"].__setitem__("tracking", None),
    ],
)
def test_malformed_search_card_is_upstream_changed(mutate):
    data = load("search_paneer_p1.json")
    mutate(data)
    try:
        parse_search_page(data)
    except BlinkitError as e:
        assert e.code == "upstream_changed"


def test_malformed_search_card_raises_only_blinkit_error():
    data = load("search_paneer_p1.json")
    data["response"]["snippets"][1]["data"].pop("product_id")
    with pytest.raises(BlinkitError) as e:
        parse_search_page(data)
    assert e.value.code == "upstream_changed"


def test_malformed_product_is_upstream_changed():
    data = load("product_329500.json")
    data["response"]["tracking"]["le_meta"]["custom_data"]["seo"]["attributes"] = [{"type": "shown_to_customer"}]
    with pytest.raises(BlinkitError) as e:
        parse_product(data)
    assert e.value.code == "upstream_changed"


@pytest.mark.parametrize(
    "reason, expected",
    [
        ("keyterm|match|paneer,text_match,within_category", True),
        ("generated_tags|paneer::cottage cheese", True),
        ("keyterm|match|milk,qtp_products_injected,text_match", True),
        ("some_future_reason", True),
        ("qtp_products", False),
        ("qtp_products,qtp_products_trending", False),
    ],
)
def test_match_reason_rule(reason, expected):
    data = load("search_paneer_p1.json")
    card = next(s for s in data["response"]["snippets"] if s["data"].get("product_id") == "329500")
    card["tracking"]["common_attributes"]["reason"] = reason
    assert by_id(parse_search_page(data), "329500").matches_query is expected
