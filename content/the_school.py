"""The School—a graphical index of the School's concepts and bodies.

A single source of truth, the ``TAXONOMY`` below, drives *both* the visual
table of contents (the "graphic") and the encyclopedia-style entries on the
``/the-school/`` page. Each concept is backed by its own Markdown file at
``content/pages/the-school/<slug>.md`` so entries can be authored—and
attributed—independently. Add a slug to a row here and drop a matching
``.md`` file in that directory, and the concept appears in both the graphic
and the entry list; the two can never drift.

Promotion is free: because every entry is already a standalone file, an entry
that outgrows this page can later be served at its own URL with no
restructuring.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.urls import NoReverseMatch, reverse

from . import loader

ENTRIES_DIR = Path(settings.BASE_DIR) / "content" / "pages" / "the-school"

# (Row label, [concept slugs in display order]). The row grouping is one
# member's mental model of the School (Gardner Gray's)—the labels and the
# membership of each row are an editorial decision for the School, not a
# technical one. Edit freely.
TAXONOMY: list[tuple[str, list[str]]] = [
    ("One by One", ["palimpsests", "passages", "traversees"]),
    ("One on Ones", ["training-analysis", "control-analyses", "advisor-meetings"]),
    ("Study Groups", ["seminars", "cartels", "reading-groups"]),
    ("All School Functions", ["days-of-assembly", "working-days"]),
    ("School Bodies", ["board", "meeting-of-the-analysts", "program-committee", "working-groups"]),
]

# Concept slug -> URL *name* of a real destination elsewhere on the site, when
# one exists. Resolved with reverse() so a renamed route fails loudly in tests
# rather than rotting into a dead link. Concepts absent here are description-only
# for now (the entry itself is the content).
DESTINATIONS: dict[str, str] = {
    "seminars": "workgroups:kind_seminars",
    "cartels": "workgroups:kind_cartels",
    "reading-groups": "workgroups:kind_reading_groups",
    "working-groups": "workgroups:kind_working_groups",
    "board": "workgroups:kind_committees",
    "program-committee": "workgroups:kind_committees",
    "palimpsests": "works:index",
    "passages": "works:index",
}

# Optional query string appended to a destination—a filter the linked page
# applies automatically. Lets one shared archive (the Works index, which reads
# ``?kind=``) serve as the destination for several blocks, each pre-filtered.
DESTINATION_QUERY: dict[str, str] = {
    "palimpsests": "kind=palimpsest",
    "passages": "kind=passage",
}


@dataclass(frozen=True)
class Entry:
    slug: str
    title: str
    author: str          # attribution byline; "" when the entry is unsigned
    body_html: str
    destination: str     # resolved URL to a real page, or "" when none


def _load_entry(slug: str, destination: str) -> Entry | None:
    """Load one concept entry from ``the-school/<slug>.md``.

    Reuses the content loader's frontmatter + Markdown machinery. Returns
    ``None`` if the file is missing, so a slug listed before its entry is
    written simply doesn't render (rather than erroring).
    """
    path = ENTRIES_DIR / f"{slug}.md"
    if not path.is_file():
        return None
    meta, body = loader._parse_frontmatter(path.read_text(encoding="utf-8"))
    return Entry(
        slug=slug,
        title=meta.get("title", slug.replace("-", " ").title()),
        author=meta.get("author", ""),
        body_html=loader._render_body(body),
        destination=destination,
    )


def build_rows() -> list[dict]:
    """Assemble the taxonomy into template-ready rows.

    Each row is ``{"label": str, "entries": [Entry, ...]}``. Rows whose
    entries are all missing are dropped.
    """
    rows: list[dict] = []
    for label, slugs in TAXONOMY:
        entries: list[Entry] = []
        for slug in slugs:
            destination = ""
            url_name = DESTINATIONS.get(slug)
            if url_name:
                try:
                    destination = reverse(url_name)
                except NoReverseMatch:
                    destination = ""
                else:
                    query = DESTINATION_QUERY.get(slug)
                    if query:
                        destination = f"{destination}?{query}"
            entry = _load_entry(slug, destination)
            if entry is not None:
                entries.append(entry)
        if entries:
            rows.append({"label": label, "entries": entries})
    return rows
