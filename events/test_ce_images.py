"""Accreditor-logo normalization (task #486)."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from events.ce_images import InvalidImage, normalize_logo


def _png_bytes(size=(400, 200), mode="RGBA", color=(10, 20, 30, 255)) -> bytes:
    img = Image.new(mode, size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_output_is_webp():
    out = normalize_logo(io.BytesIO(_png_bytes()))
    assert Image.open(io.BytesIO(out.read())).format == "WEBP"


def test_a_small_logo_is_left_at_its_own_size():
    out = normalize_logo(io.BytesIO(_png_bytes(size=(300, 120))))
    assert Image.open(io.BytesIO(out.read())).size == (300, 120)


def test_an_oversized_logo_is_fitted_inside_the_box_without_distortion():
    out = normalize_logo(io.BytesIO(_png_bytes(size=(4000, 1000))))
    width, height = Image.open(io.BytesIO(out.read())).size
    assert width <= 1200 and height <= 600
    assert width == 1200 and height == 300     # 4:1 aspect ratio preserved


def test_a_squarish_seal_is_stored_without_downsampling():
    """The real APA Approved Sponsor mark is 459x431. The former 800x400 box
    shrank it to 426x400, throwing away resolution the full-size modal (task
    #506) then wants back — and no original is retained for a logo, so that
    loss was permanent."""
    out = normalize_logo(io.BytesIO(_png_bytes(size=(459, 431))))
    assert Image.open(io.BytesIO(out.read())).size == (459, 431)


def test_transparency_survives():
    """A wordmark is dark-on-transparent; flattening it onto white would put a
    hard rectangle on the page."""
    src = io.BytesIO(_png_bytes(size=(200, 100), color=(10, 20, 30, 0)))
    out = normalize_logo(src)
    img = Image.open(io.BytesIO(out.read()))
    assert img.mode == "RGBA"
    assert img.getpixel((100, 50))[3] == 0


def test_an_opaque_logo_is_accepted():
    out = normalize_logo(io.BytesIO(_png_bytes(mode="RGB", color=(200, 30, 30))))
    assert Image.open(io.BytesIO(out.read())).format == "WEBP"


def test_a_non_image_is_rejected():
    with pytest.raises(InvalidImage):
        normalize_logo(io.BytesIO(b"this is definitely not an image"))
