"""Rendering helpers for inline-HTML documents.

Some documents have no source PDF — their content lives as markdown in
``Document.body`` and is rendered inline on the detail page. The body may
reference **site-wide values** through simple ``{{ token }}`` placeholders
(currently just the annual tuition figure) so the page always reflects the
live number without a re-edit.

Substitution is plain string replacement — no Django template engine — so
staff-authored bodies carry no template-injection surface.
"""

from __future__ import annotations

import re

import markdown
from django.utils.safestring import mark_safe

_MARKDOWN_EXTENSIONS = ["smarty", "sane_lists", "tables"]


def annual_tuition(on_date=None) -> str:
    """The current annual tuition, formatted (e.g. ``$2,500``).

    Sourced from the :class:`payments.models.TuitionPeriod` covering
    ``on_date`` (default today) — the same staff-editable per-year figure the
    tuition lifecycle uses — falling back to the most recent period. When no
    period exists at all, returns a neutral phrase that reads in-sentence.
    """
    from payments.models import TuitionPeriod

    period = TuitionPeriod.current(on_date) or TuitionPeriod.objects.first()
    if period is None:
        return "the annual tuition amount"
    return f"${period.tuition_amount:,.0f}"


#: Placeholder name → resolver. Each resolver takes ``on_date`` and returns str.
TOKENS = {
    "annual_tuition": annual_tuition,
}


def _substitute_tokens(text: str, on_date=None) -> str:
    for name, resolver in TOKENS.items():
        pattern = r"\{\{\s*" + re.escape(name) + r"\s*\}\}"
        text = re.sub(pattern, lambda _m, r=resolver: r(on_date), text)
    return text


def render_body(text: str, on_date=None):
    """Substitute site-wide tokens, then render markdown to safe HTML."""
    if not text:
        return ""
    substituted = _substitute_tokens(text, on_date)
    html = markdown.markdown(
        substituted,
        extensions=_MARKDOWN_EXTENSIONS,
        output_format="html5",
    )
    return mark_safe(html)
