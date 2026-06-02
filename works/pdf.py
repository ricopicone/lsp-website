"""Render a working document's HTML to a PDF (xhtml2pdf — pure-Python, no
system libs). Used by the Publish flow to attach a PDF to the resulting Work."""

from __future__ import annotations

from io import BytesIO

from django.template.loader import render_to_string


def render_document_pdf(*, title: str, body_html: str) -> bytes:
    from xhtml2pdf import pisa

    html = render_to_string("works/pdf/document.html",
                            {"title": title, "body_html": body_html})
    out = BytesIO()
    pisa.CreatePDF(src=html, dest=out, encoding="utf-8")
    return out.getvalue()
