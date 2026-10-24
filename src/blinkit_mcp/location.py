"""Address lookup and serviceability.

Address lookup uses Blinkit's own endpoints (found in the web app, 2026-10-24):
  1. GET /location/autoSuggest?query=<text>&lat=..&lng=.. -> candidates with a
     Google place_id. Without lat/lng Blinkit returns HTTP 400.
  2. GET /location/info?place_id=<id> -> coordinates and address.
/location/info with lat/lng always reports "not serviceable", so
serviceability comes from a product search instead.
"""

from .errors import NOT_SERVICEABLE, BlinkitError
from .models import Place, Suggestion
from .parsers import parse_place_info, parse_search_page, parse_suggestions

__all__ = ["Place", "Suggestion", "suggest_places", "place_location", "check_serviceable"]

# Bias point for autoSuggest when the caller has none (Gurugram). Results are
# not limited to this area.
DEFAULT_BIAS = (28.4595, 77.0266)
MAX_SUGGESTIONS = 5
PROBE_QUERY = "milk"  # every Blinkit store stocks milk


def suggest_places(client, text: str, bias: tuple[float, float] = DEFAULT_BIAS) -> list[Suggestion]:
    data = client.get_json("/location/autoSuggest", {"query": text, "lat": str(bias[0]), "lng": str(bias[1])})
    return parse_suggestions(data)[:MAX_SUGGESTIONS]


def place_location(client, place_id: str) -> Place:
    return parse_place_info(client.get_json("/location/info", {"place_id": place_id}))


def check_serviceable(client, lat: float, lon: float) -> str | None:
    """Return the store id serving (lat, lon). Raise not_serviceable if none."""
    page = parse_search_page(client.search(PROBE_QUERY, lat, lon))
    if not page.products:
        raise BlinkitError(NOT_SERVICEABLE, "Blinkit returned no products for this location")
    return next((p.merchant_id for p in page.products if p.merchant_id), None)
