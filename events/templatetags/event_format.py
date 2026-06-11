"""Inline formatting for member-authored event text (task #245).

Descriptions, readings, and notes are plain text, but MLA citations need
italicized book titles — ``*asterisks*`` are the authoring affordance (the
proposal form's citation style guide points members at it). Everything is
HTML-escaped first, so the only markup that survives is the ``<em>`` we emit.
"""

from __future__ import annotations

import re

from django import template
from django.template.defaultfilters import stringfilter
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

register = template.Library()

#: *text* spans — no nesting, no empty pairs, single line (a lone * stays literal).
_ITALIC = re.compile(r"\*([^*\n]+)\*")


@register.filter(needs_autoescape=True)
@stringfilter
def inline_italics(value, autoescape=True):
    """Escape, then render ``*text*`` as ``<em>text</em>``.

    Safe to chain into ``linebreaks`` — the result is marked safe so the
    paragraphs wrap it without re-escaping.
    """
    escaped = conditional_escape(value) if autoescape else value
    return mark_safe(_ITALIC.sub(r"<em>\1</em>", escaped))
