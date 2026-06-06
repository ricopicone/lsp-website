"""The Guides section — evergreen how-to pages, one Markdown file each at
``content/pages/guides/<slug>.md``, listed and ordered here.

Mirrors ``the_school.py``: a small in-code index drives a card grid and the
per-guide pages, each backed by a standalone Markdown file (frontmatter +
body) so guides can be authored and attributed independently. Add a slug to
``GUIDE_SLUGS`` and drop a matching ``.md`` file, and the guide appears.

A guide may name a *walkthrough* in its frontmatter (``checklist: profile``);
the guide page then offers a "Start this walkthrough" button that turns the
floating card into that guide's tailored steps and follows the member through
them. Walkthrough ids live in ``core.checklists``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from . import loader

GUIDES_DIR = Path(settings.BASE_DIR) / "content" / "pages" / "guides"

# Display order of the guides. A slug with no matching .md file is simply
# skipped (so you can list it here before writing it).
GUIDE_SLUGS: list[str] = [
    "profile",
    "seminars",
    "parletre",
    "cartels",
    "my-formation",
    "tuition-dues",
]


@dataclass(frozen=True)
class Guide:
    slug: str
    title: str
    summary: str
    body_html: str
    checklist: str  # walkthrough id this guide steps through, or ""


def _load(slug: str) -> Guide | None:
    if "/" in slug or ".." in slug:
        return None
    path = GUIDES_DIR / f"{slug}.md"
    if not path.is_file():
        return None
    meta, body = loader._parse_frontmatter(path.read_text(encoding="utf-8"))
    return Guide(
        slug=slug,
        title=meta.get("title", slug.replace("-", " ").title()),
        summary=meta.get("summary", ""),
        body_html=loader._render_body(body),
        checklist=meta.get("checklist", ""),
    )


def all_guides() -> list[Guide]:
    """Every guide that has a Markdown file, in display order."""
    return [g for slug in GUIDE_SLUGS if (g := _load(slug)) is not None]


def get_guide(slug: str) -> Guide | None:
    """One guide by slug (only if it's a known, listed guide)."""
    return _load(slug) if slug in GUIDE_SLUGS else None
