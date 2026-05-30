"""Markdown rendering helpers for the in-admin Help tabs."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import markdown

DOCS_DIR = Path(__file__).parent


@lru_cache(maxsize=16)
def render_doc(slug: str) -> str:
    """Render the Markdown file ``<slug>.md`` to HTML.

    Cached per-slug so the disk read + parse only happens once per
    process. Restart the app to pick up edits in development; the
    container restart on deploy handles it in production.
    """
    src = (DOCS_DIR / f"{slug}.md").read_text()
    return markdown.markdown(
        src,
        extensions=[
            "footnotes",
            "tables",
            "def_list",
            "smarty",
            "sane_lists",
            "fenced_code",
        ],
        output_format="html5",
    )
