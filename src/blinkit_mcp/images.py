"""Download product images and shrink them to a size an assistant can read."""

import io
from urllib.parse import urlparse

from PIL import Image, UnidentifiedImageError

from .errors import BAD_INPUT, UPSTREAM_CHANGED, BlinkitError

MAX_SIDE = 1500  # enough to read label text
MAX_IMAGES = 4
ALLOWED_HOST = "cdn.grofers.com"
JPEG_QUALITY = 85


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise BlinkitError(BAD_INPUT, f"only https://{ALLOWED_HOST}/ image URLs are allowed, got {url!r}")


def fetch_image(client, url: str) -> bytes:
    """Return the image at `url` as JPEG bytes, long side at most MAX_SIDE."""
    validate_url(url)
    try:
        img = Image.open(io.BytesIO(client.get_bytes(url)))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise BlinkitError(UPSTREAM_CHANGED, f"{url} is not an image")
    if img.mode != "RGB":
        background = Image.new("RGB", img.size, "white")
        rgba = img.convert("RGBA")
        background.paste(rgba, mask=rgba.getchannel("A"))
        img = background
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=JPEG_QUALITY)
    return out.getvalue()
