"""Load and save the user's delivery location."""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Location:
    address: str
    lat: float
    lon: float
    merchant_id: str | None


def config_path() -> Path:
    override = os.environ.get("BLINKIT_MCP_CONFIG")
    if override:
        return Path(override)
    return Path.home() / ".config" / "blinkit-mcp" / "config.json"


def load_location() -> Location | None:
    """Return the saved location, or None if it is not set or the file is unreadable."""
    try:
        data = json.loads(config_path().read_text())
        loc = data["location"]
        return Location(
            address=str(loc["address"]),
            lat=float(loc["lat"]),
            lon=float(loc["lon"]),
            merchant_id=None if loc.get("merchant_id") is None else str(loc["merchant_id"]),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_location(loc: Location) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"location": asdict(loc)}, indent=2))
