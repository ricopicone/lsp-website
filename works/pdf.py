"""Render a working document to a PDF (fpdf2 — pure-Python, ships wheels, no
system libraries). Used by the Publish flow to attach a PDF to the resulting
Work, with a title block carrying the document's provenance."""

from __future__ import annotations

import re

#: TipTap's StarterKit wraps list-item content in a paragraph
#: (``<li><p>text</p></li>``); fpdf2's write_html then drops the text onto its
#: own line away from the bullet. Unwrap that single inner paragraph so bullets
#: and their text stay together.
_LI_P = re.compile(r"<li>\s*<p>(.*?)</p>\s*</li>", re.DOTALL | re.IGNORECASE)


def _unwrap_list_paragraphs(html: str) -> str:
    return _LI_P.sub(r"<li>\1</li>", html or "")


def render_document_pdf(
    *,
    title: str,
    body_html: str,
    group_kind: str | None = None,
    group_name: str | None = None,
    published_date=None,
    revision: int | None = None,
) -> bytes:
    """Render ``title`` + sanitized ``body_html`` to PDF bytes, prefaced by a
    title block (title, producing group, publication date, revision).

    ``body_html`` is expected to already be sanitized to the TipTap tag subset
    (see ``workgroups.views._sanitize_document_html``).
    """
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
    from fpdf.fonts import FontFace, TextStyle

    pdf = FPDF(format="letter")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(left=20, top=20, right=20)
    pdf.add_page()

    # --- Title block ---------------------------------------------------------
    pdf.set_font("Times", "B", 26)
    pdf.set_text_color(20, 20, 20)
    pdf.multi_cell(0, 9, title or "Untitled document",
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    meta = []
    if group_name:
        meta.append(f"{group_kind or 'Group'}: {group_name}")
    if published_date is not None:
        meta.append(f"Published {published_date:%B %-d, %Y}")
    if revision:
        meta.append(f"Revision {revision}")
    if meta:
        pdf.ln(1)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(120, 120, 120)
        pdf.multi_cell(0, 5, "    ·    ".join(meta),
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(3)
    pdf.set_draw_color(205, 205, 205)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(6)

    # --- Body ----------------------------------------------------------------
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 11)

    tag_styles = {
        "h1": TextStyle(color=(17, 17, 17), font_family="Times",
                        font_size_pt=17, t_margin=4, b_margin=1.5),
        "h2": TextStyle(color=(17, 17, 17), font_family="Times",
                        font_size_pt=14, t_margin=3, b_margin=1.5),
        "h3": TextStyle(color=(17, 17, 17), font_family="Times",
                        font_size_pt=12, t_margin=3, b_margin=1),
        "h4": TextStyle(color=(17, 17, 17), font_family="Times",
                        font_size_pt=11, t_margin=2, b_margin=1),
        "blockquote": TextStyle(color=(90, 90, 90), l_margin=6,
                                t_margin=2, b_margin=2),
        "a": FontFace(color=(30, 40, 130), emphasis="UNDERLINE"),
    }
    pdf.write_html(
        _unwrap_list_paragraphs(body_html or ""),
        tag_styles=tag_styles,
        li_prefix_color=(0, 0, 0),
    )
    return bytes(pdf.output())
