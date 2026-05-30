"""Headshot image processing for the self-service profile editor.

The site frames headshots as circles and rounded squares in many places
(nav avatar, directory, event speaker cards, works tone-cards, the
Find-an-Analyst map). Rather than teach every render site about focal
points, we normalise each upload to a single centred **square** so the
existing ``object-cover`` markup just works everywhere.

Flow: the browser cropper sends the full original plus a crop rectangle in
natural-image pixels (Cropper.js ``getData()``). The server keeps the
original (so the member can re-crop later without re-uploading) and renders
the crop to a fixed-size square WebP that becomes ``Profile.headshot``.
"""

from __future__ import annotations

import io

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

# Final rendered square, in pixels. Large enough for retina avatars and the
# 144px directory-detail frame; small enough to stay light in S3.
OUTPUT_SIZE = 512

# Reject absurd uploads outright; downscale merely-large ones.
MAX_SOURCE_DIM = 6000
MAX_UPLOAD_BYTES = 12 * 1024 * 1024  # 12 MB

# Pillow format names we accept. Everything is re-encoded to WebP on the way
# out, so the stored format is uniform regardless of what was uploaded.
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF", "MPO", "HEIF", "HEIC"}


class InvalidImage(ValueError):
    """Raised when an upload is missing, unreadable, or an unsupported type."""


def _coerce_box(crop: dict | None, width: int, height: int) -> tuple[int, int, int, int] | None:
    """Turn a Cropper.js crop dict into a clamped (left, top, right, bottom).

    Returns ``None`` when there's no usable crop, in which case the caller
    falls back to a centred square of the whole image.
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


def _center_square(width: int, height: int) -> tuple[int, int, int, int]:
    """A centred square box covering the short edge of a width×height image."""
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return (left, top, left + side, top + side)


def render_headshot_square(source, crop: dict | None = None) -> ContentFile:
    """Render ``source`` (an uploaded file/blob) to a square WebP ContentFile.

    Applies EXIF orientation, crops per ``crop`` (or centre-crops when no
    crop is given or it's unusable), resizes to ``OUTPUT_SIZE``², flattens
    transparency onto white, and re-encodes as WebP. Raises ``InvalidImage``
    for unreadable or unsupported uploads.
    """
    try:
        source.seek(0)
    except (AttributeError, OSError):
        pass

    try:
        img = Image.open(source)
        img.load()
    except Exception as exc:  # Pillow raises a grab-bag of errors here.
        raise InvalidImage("Could not read the uploaded image.") from exc

    if img.format and img.format.upper() not in ALLOWED_FORMATS:
        raise InvalidImage(f"Unsupported image type: {img.format}.")

    # Honour the camera's rotation flag, then drop EXIF so we don't re-rotate.
    img = ImageOps.exif_transpose(img)

    if max(img.size) > MAX_SOURCE_DIM:
        img.thumbnail((MAX_SOURCE_DIM, MAX_SOURCE_DIM), Image.LANCZOS)

    width, height = img.size
    box = _coerce_box(crop, width, height) or _center_square(width, height)

    # Force the crop to a square so the output isn't distorted — the cropper
    # enforces this client-side, but a hand-rolled POST might not.
    left, top, right, bottom = box
    bw, bh = right - left, bottom - top
    if bw != bh:
        side = min(bw, bh)
        right = left + side
        bottom = top + side

    img = img.crop((left, top, right, bottom))

    if img.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    else:
        img = img.convert("RGB")

    img = img.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=82, method=6)
    return ContentFile(buf.getvalue())
