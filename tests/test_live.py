"""End-to-end test against the real blinkit.com. Run: BLINKIT_LIVE=1 uv run pytest tests/test_live.py"""

import os

import pytest
from mcp.server.mcpserver import Image

from blinkit_mcp import server

pytestmark = pytest.mark.skipif(os.environ.get("BLINKIT_LIVE") != "1", reason="set BLINKIT_LIVE=1 to run")


def test_live_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("BLINKIT_MCP_CONFIG", str(tmp_path / "config.json"))

    loc = server.set_location(lat=28.4595, lon=77.0266)
    assert loc["status"] == "ok", loc

    found = server.search_products("paneer", limit=5)
    assert found["status"] == "found", found
    assert found["count"] == 5
    first = found["products"][0]
    assert first["price"] and first["image_url"]

    detail = server.get_product(first["product_id"])
    assert detail["status"] == "ok", detail
    assert len(detail["images"]) >= 1

    shown = server.view_images(product_id=first["product_id"], indexes=[0])
    assert isinstance(shown[1], Image), shown

    assert server.search_products("xqzvbnm")["status"] == "no_match"
    assert server.set_location(lat=33.5, lon=79.0)["status"] == "not_serviceable"
