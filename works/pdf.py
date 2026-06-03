"""Render a working document to a PDF (fpdf2 — pure-Python, ships wheels, no
system libraries). Used by the Publish flow to attach a PDF to the resulting
Work, with a title block carrying the document's provenance.

Fonts are vendored Unicode TrueType (DejaVu, in ``works/fonts/``) so documents
containing characters outside latin-1 (accents, non-Latin scripts) render
rather than crashing the core latin-1 fonts."""

from __future__ import annotations

import re
from pathlib import Path

_FONTS = Path(__file__).resolve().parent / "fonts"

#: TipTap's StarterKit wraps list-item content in a paragraph
#: (``<li><p>text</p></li>``); fpdf2's write_html then drops the text onto its
#: own line away from the bullet. Unwrap that single inner paragraph so bullets
#: and their text stay together.
_LI_P = re.compile(r"<li>\s*<p>(.*?)</p>\s*</li>", re.DOTALL | re.IGNORECASE)


def _unwrap_list_paragraphs(html: str) -> str:
    return _LI_P.sub(r"<li>\1</li>", html or "")


def _register_fonts(pdf) -> None:
    pdf.add_font("DejaVu", "", str(_FONTS / "DejaVuSans.ttf"))
    pdf.add_font("DejaVu", "B", str(_FONTS / "DejaVuSans-Bold.ttf"))
    pdf.add_font("DejaVu", "I", str(_FONTS / "DejaVuSans-Oblique.ttf"))
    pdf.add_font("DejaVu", "BI", str(_FONTS / "DejaVuSans-BoldOblique.ttf"))
    pdf.add_font("DejaVuSerif", "", str(_FONTS / "DejaVuSerif.ttf"))
    pdf.add_font("DejaVuSerif", "B", str(_FONTS / "DejaVuSerif-Bold.ttf"))


def render_document_pdf(
    *,
    title: str,
    body_html: str,
    group_kind: str | None = None,
    group_name: str | None = None,
    members: list[str] | None = None,
    published_date=None,
    revision: int | None = None,
) -> bytes:
    """Render ``title`` + sanitized ``body_html`` to PDF bytes, prefaced by a
    title block (title, producing group, members, publication date, revision).

    ``body_html`` is expected to already be sanitized to the TipTap tag subset
    (see ``workgroups.views._sanitize_document_html``).
    """
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
    from fpdf.fonts import FontFace, TextStyle

    pdf = FPDF(format="letter")
    _register_fonts(pdf)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(left=20, top=20, right=20)
    pdf.add_page()

    # --- Title block ---------------------------------------------------------
    pdf.set_font("DejaVuSerif", "B", 24)
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
        pdf.ln(1.5)
        pdf.set_font("DejaVu", "", 10)
        pdf.set_text_color(120, 120, 120)
        pdf.multi_cell(0, 5, "    ·    ".join(meta),
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if members:
        pdf.ln(0.5)
        pdf.set_font("DejaVu", "", 9.5)
        pdf.set_text_color(140, 140, 140)
        pdf.multi_cell(0, 4.6, "Members: " + ", ".join(members),
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(3)
    pdf.set_draw_color(205, 205, 205)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(6)

    # --- Body ----------------------------------------------------------------
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("DejaVu", "", 11)

    tag_styles = {
        "h1": TextStyle(color=(17, 17, 17), font_family="DejaVuSerif",
                        font_size_pt=17, t_margin=4, b_margin=1.5),
        "h2": TextStyle(color=(17, 17, 17), font_family="DejaVuSerif",
                        font_size_pt=14, t_margin=3, b_margin=1.5),
        "h3": TextStyle(color=(17, 17, 17), font_family="DejaVuSerif",
                        font_size_pt=12, t_margin=3, b_margin=1),
        "h4": TextStyle(color=(17, 17, 17), font_family="DejaVuSerif",
                        font_size_pt=11, t_margin=2, b_margin=1),
        "blockquote": TextStyle(color=(90, 90, 90), l_margin=6,
                                t_margin=2, b_margin=2),
        "a": FontFace(color=(30, 40, 130), emphasis="UNDERLINE"),
        # Tighten list spacing (defaults leave a loose gap above the first item)
        # and keep items snug; the marker sits on the text baseline.
        "ul": TextStyle(t_margin=1, b_margin=1),
        "ol": TextStyle(t_margin=1, b_margin=1),
        "li": TextStyle(l_margin=5, t_margin=0.5, b_margin=0.5),
        # Keep code in the Unicode family (default Courier is latin-1 only).
        "code": FontFace(family="DejaVu"),
        "pre": TextStyle(font_family="DejaVu", t_margin=2, b_margin=2),
    }
    pdf.write_html(
        _unwrap_list_paragraphs(body_html or ""),
        font_family="DejaVu",
        tag_styles=tag_styles,
        li_prefix_color=(0, 0, 0),
        ul_bullet_char="•",
    )
    return bytes(pdf.output())
