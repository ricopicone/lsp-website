"""Feature-image processing for an event (task #504).

Neither existing pipeline fits. ``accounts.images`` force-crops to a centred
square, which is right for an avatar and wrong for a canvas; ``ce_images``
never crops at all, which is right for a wordmark and leaves the page holding
whatever shape arrived. Here the shape is settled at upload into a *range*
(square through 2.5:1), so a square poster survives intact while every render
site still only ever meets a shape it can lay out.
"""

from __future__ import annotations

import io

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

#: Narrowest and widest a rendered feature image may be. A square keeps a poster
#: or an album cover intact; past 2.5:1 the band stops reading as an image and
#: starts reading as a rule drawn across the page.
MIN_RATIO = 1.0
MAX_RATIO = 2.5

#: The render fits inside this box at whatever ratio the crop produced, so a
#: 2.5:1 lands 1600x640 and a square lands 900x900. Displayed at most 340 CSS
#: pixels tall, which leaves retina headroom.
RENDER_BOX = (1600, 900)

#: The retained original is bounded too: re-cropping later must stay possible,
#: but a 20 MB phone photo should not sit in S3 forever to make it so.
ORIGINAL_BOX = (2400, 2400)

#: Below this the band shows a blur, which looks worse than no image at all.
MIN_RENDER_WIDTH = 800

#: Downscale a huge source before cropping; reject an enormous file before
#: decoding it at all.
MAX_SOURCE_DIM = 6000
MAX_UPLOAD_BYTES = 12 * 1024 * 1024

#: Pillow format names we accept. Everything is re-encoded to WebP on the way
#: out, so the stored format is uniform regardless of what was uploaded.
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF", "MPO", "HEIF", "HEIC"}


class InvalidImage(ValueError):
    """Raised when an upload is missing, unreadable, unsupported, or too small."""


def _open(source) -> Image.Image:
    """Decode ``source``, honour its EXIF rotation, and bound its dimensions."""
    try:
        source.seek(0)
    except (AttributeError, OSError):
        pass

    try:
        img = Image.open(source)
        img.load()
    except Exception as exc:  # Pillow raises a grab-bag of errors here.
        raise InvalidImage("Could not read that image.") from exc

    if img.format and img.format.upper() not in ALLOWED_FORMATS:
        raise InvalidImage(f"Unsupported image type: {img.format}.")

    img = ImageOps.exif_transpose(img)
    if max(img.size) > MAX_SOURCE_DIM:
        img.thumbnail((MAX_SOURCE_DIM, MAX_SOURCE_DIM), Image.LANCZOS)
    return img


def _coerce_box(crop: dict | None, width: int, height: int) -> tuple[int, int, int, int] | None:
    """Turn a Cropper.js rect into a clamped (left, top, right, bottom).

    Returns ``None`` when there's no usable crop, in which case the caller falls
    back to the whole image.
    """
    if not crop:
        return None
    try:
        x = int(round(float(crop.get("x", 0))))
        y = int(round(float(crop.get("y", 0))))
        w = int(round(float(crop.get("width", 0))))
        h = int(round(float(crop.get("height", 0))))
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    left = max(0, min(x, width))
    top = max(0, min(y, height))
    right = max(left + 1, min(x + w, width))
    bottom = max(top + 1, min(y + h, height))
    return (left, top, right, bottom)


def _clamp_ratio(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Shrink ``box`` about its centre until its ratio sits inside the range.

    The cropper enforces this client-side; a hand-rolled POST, a no-JS upload,
    and the whole-image default all arrive here instead.
    """
    left, top, right, bottom = box
    w, h = right - left, bottom - top
    ratio = w / h
    if ratio > MAX_RATIO:
        new_w = int(round(h * MAX_RATIO))
        left += (w - new_w) // 2
        right = left + new_w
    elif ratio < MIN_RATIO:
        new_h = int(round(w / MIN_RATIO))
        top += (h - new_h) // 2
        bottom = top + new_h
    return (left, top, right, bottom)


def render(source, crop: dict | None = None) -> ContentFile:
    """Render ``source`` to a bounded WebP ``ContentFile`` inside the ratio range.

    With no usable ``crop`` the whole image is used, narrowed about its centre
    only as far as the range demands. Raises :class:`InvalidImage`.
    """
    img = _open(source)
    width, height = img.size
    box = _clamp_ratio(_coerce_box(crop, width, height) or (0, 0, width, height))
    img = img.crop(box)

    if img.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    else:
        img = img.convert("RGB")

    # thumbnail() never upscales, so a small crop stays small and is refused
    # below rather than blown up into blur.
    img.thumbnail(RENDER_BOX, Image.LANCZOS)
    if img.width < MIN_RENDER_WIDTH:
        raise InvalidImage(
            "That image is too small. It needs to be at least "
            f"{MIN_RENDER_WIDTH} pixels wide after cropping.",
        )

    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=82, method=6)
    return ContentFile(buf.getvalue())


def bound_original(source) -> ContentFile:
    """Re-encode ``source`` as a bounded WebP, kept for re-cropping later."""
    img = _open(source)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    img.thumbnail(ORIGINAL_BOX, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=88, method=6)
    return ContentFile(buf.getvalue())
