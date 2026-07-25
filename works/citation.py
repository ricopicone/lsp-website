"""Chicago author-date citation rendering for external-publication Works.

Pure functions over a ``Work``: build an ordered list of *segments*
(text, italic?, href?) and render them twice — as escaped HTML (site
display) and as plain text (the copy-to-clipboard string). Degrades
gracefully: absent fields are skipped, punctuation never dangles.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe


@dataclass
class Seg:
    text: str
    italic: bool = False
    href: str = ""


def _author_names(work) -> list[str]:
    """Byline names in order, the first Chicago-inverted ("Last, First")."""
    names: list[str] = []
    for i, wa in enumerate(
        work.authorships.select_related("user").order_by("display_order")
    ):
        u = wa.user
        full = f"{u.first_name} {u.last_name}".strip()
        if i == 0 and u.last_name:
            names.append(f"{u.last_name}, {u.first_name}".strip().strip(","))
        elif full:
            names.append(full)
    if work.external_authors:
        names.extend(t.strip() for t in work.external_authors.split(",") if t.strip())
    return names


def _join_names(names: list[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + ", and " + names[-1]


def _year(work) -> str:
    return str(work.publication_date.year) if work.publication_date else "n.d."


def _vol_issue_pages(work) -> str:
    """"12 (2): 33–58" with any subset present."""
    vi = work.volume
    if work.issue:
        vi = f"{vi} ({work.issue})" if vi else f"({work.issue})"
    if work.pages:
        return f"{vi}: {work.pages}" if vi else work.pages
    return vi


def _sentence(segs: list[Seg]) -> list[Seg]:
    """Terminate the last segment with a period unless already punctuated."""
    if segs and segs[-1].text and segs[-1].text[-1] not in ".!?”":
        last = segs[-1]
        if last.italic or last.href:
            segs.append(Seg("."))  # keep the period roman, outside italics/links
        else:
            segs[-1] = Seg(last.text + ".", last.italic, last.href)
    return segs


def _body_segments(work) -> list[Seg]:
    """Everything after authors+year+title, per publication type."""
    T = type(work).ExternalType
    kind = work.external_type
    segs: list[Seg] = []
    vip = _vol_issue_pages(work)

    if kind == T.ARTICLE or (
        not kind and work.container_title and not work.publisher
    ):
        if work.container_title:
            segs.append(Seg(work.container_title, italic=True))
        if vip:
            if segs:
                segs.append(Seg(" "))
            segs.append(Seg(vip))
        return _sentence(segs)

    if kind == T.CHAPTER:
        if work.container_title:
            segs.append(Seg("In "))
            segs.append(Seg(work.container_title, italic=True))
        if work.editors:
            segs.append(Seg(f", edited by {work.editors}"))
        if work.translators:
            segs.append(Seg(f", translated by {work.translators}"))
        if work.pages:
            segs.append(Seg(f", {work.pages}"))
        _sentence(segs)
        if work.publisher:
            if segs:
                segs.append(Seg(" "))
            segs.extend(_sentence([Seg(work.publisher)]))
        return segs

    # Book / edited volume / other: container (other), edition, eds/trans,
    # publisher — each its own short sentence.
    if work.container_title:
        segs.extend(_sentence([Seg(work.container_title, italic=True)]) + [Seg(" ")])
        if vip:
            segs.extend(_sentence([Seg(vip)]) + [Seg(" ")])
    if work.editors and kind != T.EDITED_VOLUME:
        segs.extend(_sentence([Seg(f"Edited by {work.editors}")]) + [Seg(" ")])
    if work.translators:
        segs.extend(_sentence([Seg(f"Translated by {work.translators}")]) + [Seg(" ")])
    if work.edition:
        segs.extend(_sentence([Seg(work.edition)]) + [Seg(" ")])
    if work.publisher:
        segs.extend(_sentence([Seg(work.publisher)]))
    while segs and not segs[-1].text.strip():
        segs.pop()
    return segs


def _title_segments(work) -> list[Seg]:
    T = type(work).ExternalType
    quoted = work.external_type in (T.ARTICLE, T.CHAPTER) or (
        not work.external_type and work.container_title
    )
    if quoted:
        return [Seg(f"“{work.title}.”")]
    return _sentence([Seg(work.title, italic=True)])


def _full_segments(work) -> list[Seg]:
    T = type(work).ExternalType
    segs: list[Seg] = []
    names = _author_names(work)
    if names:
        authors = _join_names(names)
        if work.external_type == T.EDITED_VOLUME:
            authors += ", eds" if len(names) > 1 else ", ed"
        segs.extend(_sentence([Seg(authors)]) + [Seg(" ")])
    segs.extend(_sentence([Seg(_year(work))]) + [Seg(" ")])
    segs.extend(_title_segments(work))
    body = _body_segments(work)
    if body:
        segs.append(Seg(" "))
        segs.extend(body)
    if work.doi:
        segs.append(Seg(" "))
        segs.append(Seg(work.doi_url, href=work.doi_url))
        segs.append(Seg("."))
    return segs


def _render_html(segs: list[Seg]) -> SafeString:
    out = []
    for s in segs:
        piece = escape(s.text)
        if s.italic:
            piece = f"<i>{piece}</i>"
        if s.href:
            piece = (
                f'<a href="{escape(s.href)}" class="link" target="_blank" '
                f'rel="noopener">{piece}</a>'
            )
        out.append(piece)
    return mark_safe("".join(out))


def _render_text(segs: list[Seg]) -> str:
    return "".join(s.text for s in segs)


def citation_html(work) -> SafeString:
    """The full Chicago author-date citation, as safe HTML."""
    return _render_html(_full_segments(work))


def citation_text(work) -> str:
    """Plain-text twin of :func:`citation_html`, for copy-to-clipboard."""
    return _render_text(_full_segments(work))


def source_html(work) -> SafeString:
    """The venue part alone (no authors, year, or title), for headers/cards."""
    segs = _body_segments(work)
    return _render_html(segs) if segs else mark_safe("")
