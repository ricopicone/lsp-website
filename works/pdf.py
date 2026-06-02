"""Render a working document's HTML to a PDF (fpdf2 — pure-Python, ships
wheels, no system libraries). Used by the Publish flow to attach a PDF to the
resulting Work."""

from __future__ import annotations

import html as _html


def render_document_pdf(*, title: str, body_html: str) -> bytes:
    """Render ``title`` + sanitized ``body_html`` to PDF bytes.

    ``body_html`` is expected to already be sanitized to the TipTap tag subset
    (see ``workgroups.views._sanitize_document_html``); fpdf2's ``write_html``
    renders that subset (headings, paragraphs, bold/italic, links, lists).
    """
    from fpdf import FPDF

    pdf = FPDF(format="letter")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_margins(left=18, top=18, right=18)
    heading = f"<h1>{_html.escape(title or 'Untitled document')}</h1>"
    pdf.write_html(heading + (body_html or ""))
    return bytes(pdf.output())
