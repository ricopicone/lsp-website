"""Accreditor-logo processing (task #486).

Deliberately *not* ``accounts.images``: that pipeline force-crops to a centred
square and flattens transparency onto white, which is right for a headshot and
would mangle a wordmark. A logo keeps its aspect ratio and its alpha channel,
and is merely bounded so one faculty member's 4000px PNG does not become the
heaviest asset on the event page.
"""

from __future__ import annotations

import io

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

#: Largest stored logo, in pixels. Rendered at max 144x48 CSS pixels, so this
#: leaves generous headroom for retina without storing anything absurd.
MAX_BOX = (800, 400)

#: Reject an upload larger than this outright, before decoding it.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MB

#: Most logos one organization may carry. Lives here beside the other upload
#: limits so every bound on a logo is in one file.
MAX_LOGOS = 10

#: Pillow format names we accept. Everything is re-encoded to WebP on the way
#: out, so the stored format is uniform regardless of what was uploaded.
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF"}


class InvalidImage(ValueError):
    """Raised when an upload is missing, unreadable, or an unsupported type."""


def normalize_logo(source) -> ContentFile:
    """Render ``source`` to a WebP ``ContentFile`` bounded by :data:`MAX_BOX`.

    Preserves aspect ratio and transparency. Raises :class:`InvalidImage` for
    unreadable or unsupported uploads.
    """
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
    # RGBA throughout: WebP carries alpha, and a logo is usually a dark
    # wordmark on transparency.
    img = img.convert("RGBA")
    # thumbnail() is a no-op when the image already fits, which is what we want
    # — never upscale a small logo into blur.
    img.thumbnail(MAX_BOX, Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=90, method=6)
    return ContentFile(buf.getvalue())
