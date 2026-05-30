"""Template helpers for the works catalog.

``tone_for`` picks a stable muted color from a string (the work's
title), so works without an uploaded cover image render a deterministic
tone-card rather than a generic placeholder. The palette is
intentionally muted so cards sit together without visual chaos.
"""

from __future__ import annotations

import hashlib

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


# Hand-picked muted palette (HSL with saturation ~22%, lightness ~58%).
# Range spans warm-to-cool so the catalog has variety without any
# single card screaming for attention.
PALETTE: list[str] = [
    "#a8967e",  # taupe
    "#9c8a8a",  # rose-brown
    "#7e9892",  # sage
    "#8a8fa3",  # slate-blue
    "#a39078",  # khaki
    "#988aa3",  # dusk-violet
    "#7a98a3",  # blue-grey
    "#a39078",  # sand
    "#8aa389",  # olive
    "#a37e95",  # mauve
]


def _hash_int(s: str) -> int:
    return int(hashlib.sha256(s.encode("utf-8")).hexdigest(), 16)


@register.simple_tag
def tone_for(title: str) -> str:
    """Return a deterministic muted color hex for ``title``."""
    if not title:
        return PALETTE[0]
    return PALETTE[_hash_int(title) % len(PALETTE)]


@register.simple_tag
def tone_style(title: str) -> str:
    """Return an inline ``style="background-color: …"`` for ``title``."""
    return mark_safe(f'style="background-color: {tone_for(title)}"')
