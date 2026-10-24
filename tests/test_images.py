import io

import pytest
from PIL import Image

from blinkit_mcp.errors import BlinkitError
from blinkit_mcp.images import MAX_IMAGES, MAX_SIDE, fetch_image, validate_url

URL = "https://cdn.grofers.com/da/cms-assets/cms/product/a.jpg"


def png(size, mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, size).save(buf, "PNG")
    return buf.getvalue()


class FakeClient:
    def __init__(self, data=b""):
        self.data = data
        self.urls = []

    def get_bytes(self, url):
        self.urls.append(url)
        return self.data


def opened(data):
    img = Image.open(io.BytesIO(data))
    return img.format, img.size


def test_limits():
    assert (MAX_SIDE, MAX_IMAGES) == (1500, 4)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/a.jpg",
        "http://cdn.grofers.com/a.jpg",
        "https://cdn.grofers.com.evil.com/a.jpg",
        "file:///etc/passwd",
        "not a url",
    ],
)
def test_rejects_other_urls(url):
    client = FakeClient(png((10, 10)))
    with pytest.raises(BlinkitError) as e:
        fetch_image(client, url)
    assert e.value.code == "bad_input"
    assert client.urls == []


def test_validate_accepts_cdn():
    validate_url(URL)


def test_large_image_is_shrunk():
    assert opened(fetch_image(FakeClient(png((3000, 2000))), URL)) == ("JPEG", (1500, 1000))


def test_tall_image_is_shrunk():
    assert opened(fetch_image(FakeClient(png((1000, 4500))), URL)) == ("JPEG", (333, 1500))


def test_small_image_unchanged():
    assert opened(fetch_image(FakeClient(png((800, 600))), URL)) == ("JPEG", (800, 600))


def test_png_with_alpha_converts():
    assert opened(fetch_image(FakeClient(png((50, 40), "RGBA")), URL)) == ("JPEG", (50, 40))


def test_not_an_image_is_upstream_changed():
    with pytest.raises(BlinkitError) as e:
        fetch_image(FakeClient(b"<html>nope</html>"), URL)
    assert e.value.code == "upstream_changed"
