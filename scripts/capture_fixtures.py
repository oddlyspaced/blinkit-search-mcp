"""Save live Blinkit responses into tests/fixtures for parser tests.

Run: uv run python scripts/capture_fixtures.py
"""

import json
from pathlib import Path

from blinkit_mcp.client import BlinkitClient
from blinkit_mcp.errors import BlinkitError

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
GURUGRAM = (28.4595, 77.0266)
# Remote Ladakh. (26.9, 70.9 looks remote but is Jaisalmer city, which Blinkit serves.)
UNSERVICEABLE = (33.5, 79.0)

SEARCHES = {
    "search_nomatch.json": ("xqzvbnm", GURUGRAM),
    "search_milk_gurugram.json": ("milk", GURUGRAM),
}


def card_counts(data: dict) -> tuple[int, int]:
    organic = ads = 0
    for s in data.get("response", {}).get("snippets", []):
        if s.get("widget_type") != "product_card_snippet_type_2":
            continue
        attrs = s.get("tracking", {}).get("common_attributes", {})
        if attrs.get("badge") == "AD":
            ads += 1
        else:
            organic += 1
    return organic, ads


def save(name: str, data: dict) -> None:
    (FIXTURES / name).write_text(json.dumps(data, ensure_ascii=False))


def main() -> None:
    client = BlinkitClient()
    for name, (query, (lat, lon)) in SEARCHES.items():
        data = client.search(query, lat, lon)
        save(name, data)
        organic, ads = card_counts(data)
        print(f"{name}: organic={organic} ads={ads}")
    try:
        client.search("milk", *UNSERVICEABLE)
        print("WARNING: search at UNSERVICEABLE location succeeded")
    except BlinkitError as exc:
        print("search at unserviceable location ->", exc.code)
    try:
        data = client.product("329500", *UNSERVICEABLE)
    except BlinkitError as exc:
        data = {"error": exc.code}
    save("product_unstocked.json", data)
    print("product_unstocked.json:", "error " + data["error"] if "error" in data else "product data saved")


if __name__ == "__main__":
    main()
