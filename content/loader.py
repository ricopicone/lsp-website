"""Load Markdown pages from ``content/pages/<slug>.md`` and render to HTML.

Each ``.md`` page can carry frontmatter as a YAML-ish block at the top:

    ---
    title: About the School
    summary: A short description for SEO and link previews.
    ---

The rest is body content rendered with python-markdown. Headings, lists,
links, footnotes, tables, and definition lists are supported; HTML in the
source is preserved (we author these pages ourselves, no untrusted input).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import markdown
from django.conf import settings

PAGES_DIR = Path(settings.BASE_DIR) / "content" / "pages"
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class Page:
    slug: str
    title: str
    summary: str
    body_html: str


def _parse_frontmatter(src: str) -> tuple[dict[str, str], str]:
    """Tiny YAML-ish frontmatter parser — `key: value` lines, no nesting.

    Avoids adding pyyaml; our pages don't need anything richer.
    """
    m = FRONTMATTER_RE.match(src)
    if not m:
        return {}, src
    block = m.group(1)
    meta: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, src[m.end():]


def _render_body(md_source: str) -> str:
    return markdown.markdown(
        md_source,
        extensions=[
            "footnotes",
            "tables",
            "def_list",
            "smarty",          # curly quotes, em dashes
            "sane_lists",
        ],
        output_format="html5",
    )


@lru_cache(maxsize=64)
def load(slug: str) -> Page | None:
    """Load a page by slug. Cached in-process so disk hits are one-shot.

    Returns ``None`` if the page doesn't exist.
    """
    if "/" in slug or ".." in slug:
        return None  # Defensive — slug should be a flat name.
    path = PAGES_DIR / f"{slug}.md"
    if not path.is_file():
        return None
    src = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(src)
    return Page(
        slug=slug,
        title=meta.get("title", slug.replace("-", " ").title()),
        summary=meta.get("summary", ""),
        body_html=_render_body(body),
    )


def clear_cache() -> None:
    """For tests / dev: drop the in-process page cache."""
    load.cache_clear()
