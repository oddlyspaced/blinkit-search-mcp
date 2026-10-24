"""Data shapes returned by the parsers and the MCP tools."""

from dataclasses import dataclass, field


@dataclass
class Product:
    product_id: str
    name: str
    brand: str | None
    pack_size: str | None
    price: float | None
    mrp: float | None
    discount_pct: int
    in_stock: bool
    inventory: int | None
    image_url: str | None
    url: str
    product_type: str | None
    sponsored: bool
    # True when Blinkit's own match reason says the item matched the query.
    # Ads and "popular items" filler have no match reason.
    matches_query: bool
    merchant_id: str | None


@dataclass
class SearchPage:
    products: list[Product]
    actual_query: str | None
    next_url: str | None


@dataclass
class ProductDetail:
    product: Product
    images: list[str] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass
class Suggestion:
    title: str
    subtitle: str
    place_id: str


@dataclass
class Place:
    address: str
    lat: float
    lon: float
