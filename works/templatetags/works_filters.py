"""Template helpers for the works catalog.

The vibe-card is a fallback for works without an uploaded cover_image.
Each work gets a deterministic muted background tone (``tone_for``)
overlaid with a generative SVG of abstract shapes (``vibe_shapes``).
Authors are surfaced on top in the template — see _tone_card.html.

Determinism (seeded from the title) means a given work always has the
same vibe, even across page loads and devices.
"""

from __future__ import annotations

import hashlib
import random

from django import template
from django.utils.html import format_html
from django.utils.safestring import SafeString, mark_safe

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


def _seeded_random(title: str) -> random.Random:
    """Deterministic PRNG seeded by ``title`` so the vibe is stable."""
    return random.Random(_hash_int(title or "x"))


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


@register.simple_tag
def vibe_shapes(title: str) -> SafeString:
    """Inline SVG: deterministic abstract shapes seeded from ``title``.

    Composes 5-9 lightweight shapes (circles, lines, rectangles) at
    varying opacities — light enough that they read as texture, not as
    figurative content. Designed to overlay a ``tone_for`` background.
    """
    rng = _seeded_random(title)
    n = rng.randint(5, 9)

    parts: list[str] = []
    for _ in range(n):
        kind = rng.choices(
            ["circle", "circle", "circle", "line", "rect"],
            k=1,
        )[0]
        # Light shapes (white-ish) and dark shapes (near-black) at low
        # opacity blend naturally with the tone base.
        color = rng.choice(["#ffffff", "#ffffff", "#ffffff", "#000000"])
        if kind == "circle":
            cx = rng.randint(-15, 115)
            cy = rng.randint(-15, 115)
            r = rng.randint(8, 32)
            opacity = rng.uniform(0.06, 0.20)
            parts.append(
                f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}" '
                f'opacity="{opacity:.2f}"/>'
            )
        elif kind == "line":
            x1, y1 = rng.randint(-10, 110), rng.randint(-10, 110)
            x2, y2 = rng.randint(-10, 110), rng.randint(-10, 110)
            opacity = rng.uniform(0.10, 0.25)
            sw = rng.choice([0.4, 0.6, 0.8])
            parts.append(
                f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                f'stroke="{color}" stroke-width="{sw}" opacity="{opacity:.2f}"/>'
            )
        else:  # rect
            x = rng.randint(-10, 80)
            y = rng.randint(-10, 80)
            w = rng.randint(10, 35)
            h = rng.randint(10, 35)
            opacity = rng.uniform(0.05, 0.16)
            parts.append(
                f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
                f'fill="{color}" opacity="{opacity:.2f}"/>'
            )

    return format_html(
        '<svg viewBox="0 0 100 100" preserveAspectRatio="none" '
        'class="absolute inset-0 w-full h-full pointer-events-none">{}</svg>',
        mark_safe("".join(parts)),
    )
