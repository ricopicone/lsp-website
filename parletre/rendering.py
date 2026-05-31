"""Safe rendering of member-authored Markdown for Parlêtre.

Posts are written by members, so their Markdown must be sanitised before it
reaches a template: the ``markdown`` library passes raw HTML and arbitrary
link schemes straight through (an XSS vector — e.g. inline ``<script>`` or
``[x](javascript:…)``). We render Markdown to HTML, then run it through nh3
(Rust *ammonia*), which drops disallowed tags/attributes and unsafe URL
schemes, and forces a safe ``rel`` on links.
"""

from __future__ import annotations

import markdown as _markdown
import nh3
from django.utils.safestring import mark_safe

#: Tags allowed in rendered posts: prose, basic formatting, links, lists,
#: blockquotes, code, headings, and tables. No raw block HTML, no images
#: (attachments arrive as a first-class feature later, not via Markdown).
_ALLOWED_TAGS = {
    "p", "br", "hr",
    "strong", "b", "em", "i", "del", "s",
    "a", "code", "pre", "blockquote",
    "ul", "ol", "li",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "thead", "tbody", "tr", "th", "td",
}
#: ``rel`` is managed by nh3 via ``link_rel`` below, so it is *not* listed here.
_ALLOWED_ATTRS = {"a": {"href", "title"}}
_URL_SCHEMES = {"http", "https", "mailto"}
_MARKDOWN_EXTENSIONS = ["fenced_code", "sane_lists", "tables", "nl2br", "smarty"]


def render_markdown(text: str) -> str:
    """Render member-authored Markdown to sanitised, safe HTML."""
    if not text:
        return ""
    html = _markdown.markdown(
        text, extensions=_MARKDOWN_EXTENSIONS, output_format="html5"
    )
    clean = nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        url_schemes=_URL_SCHEMES,
        link_rel="noopener nofollow ugc",
    )
    return mark_safe(clean)
