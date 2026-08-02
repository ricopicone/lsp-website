"""Guard against multi-line Django ``{# #}`` comments leaking onto the page.

Django's ``{# #}`` comment is **single-line only**: a ``{#`` whose matching
``#}`` is on a later line is not treated as a comment, so its text renders
straight to the page. Multi-line notes must use
``{% comment %}``/``{% endcomment %}`` instead.

This gotcha shipped to production twice on the landing page; this test makes
it impossible to ship again. It reads files only (no DB).
"""
from pathlib import Path

from django.conf import settings

# Directories that are not our source templates (vendored, generated, copies).
EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "node_modules", ".claude", ".claude-worktrees",
    "staticfiles", "htmlcov", "dist", "build",
}


def _template_files():
    base = Path(settings.BASE_DIR)
    for path in base.rglob("*.html"):
        if any(part in EXCLUDE_DIRS for part in path.relative_to(base).parts):
            continue
        yield path


def _leaking_comment_lines(text):
    """Yield 1-based line numbers where a ``{#`` opens without a ``#}`` closing
    it on the same line — i.e. a multi-line comment that will leak."""
    for lineno, line in enumerate(text.splitlines(), start=1):
        i = 0
        while (open_at := line.find("{#", i)) != -1:
            close_at = line.find("#}", open_at + 2)
            if close_at == -1:
                yield lineno
                break
            i = close_at + 2


def test_no_multiline_hash_comments_in_templates():
    offenders = []
    for path in _template_files():
        for lineno in _leaking_comment_lines(path.read_text(encoding="utf-8")):
            offenders.append(f"{path}:{lineno}")
    assert not offenders, (
        "Multi-line {# #} comments leak onto the rendered page "
        "(Django {# #} is single-line only). "
        "Use {% comment %} / {% endcomment %} instead. Offending lines:\n  "
        + "\n  ".join(offenders)
    )


def test_only_the_shared_partial_renders_messages():
    """Messages render once, from core/_messages.html via core/base.html.

    A second loop in a page template prints every message twice, and the habit
    that produced 30 of them was copying a neighbouring template.
    """
    offenders = []
    for path in _template_files():
        if path.name == "_messages.html":
            continue
        text = path.read_text(encoding="utf-8")
        if "for m in messages" in text or "for message in messages" in text:
            offenders.append(str(path.relative_to(Path(settings.BASE_DIR))))
    assert not offenders, (
        "Messages are rendered once, by core/_messages.html (included from "
        "core/base.html). Remove the loop from:\n  " + "\n  ".join(offenders)
    )
