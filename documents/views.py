"""Documents app views.

The index renders the (current) Document list grouped by category as
cards. Detail pages show the longer markdown description plus a
download link. The download view exists so members-only documents can
be gated — public documents could be served directly from S3, but
routing all PDFs through the same view keeps the permission check in
one place.
"""

from __future__ import annotations

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render

from .models import Document


def index(request):
    qs = Document.for_user(request.user).order_by("category", "display_order", "title")

    # Group by category, preserving CATEGORY_ORDER so sections appear in a
    # deliberate order (Governance first, Reference last) regardless of
    # alphabetic order.
    by_category: dict[str, list[Document]] = {c: [] for c in Document.CATEGORY_ORDER}
    for doc in qs:
        by_category.setdefault(doc.category, []).append(doc)

    sections = [
        {
            "key": cat,
            "label": Document.Category(cat).label,
            "documents": by_category[cat],
        }
        for cat in Document.CATEGORY_ORDER
        if by_category[cat]
    ]
    return render(request, "documents/index.html", {"sections": sections})


def detail(request, slug):
    doc = get_object_or_404(Document, slug=slug)
    if not doc.visible_to(request.user):
        raise Http404()
    older = doc.supersedes.all().order_by("-effective_date") if doc.is_current else []
    return render(
        request,
        "documents/detail.html",
        {"doc": doc, "older_versions": older},
    )


def download(request, slug):
    doc = get_object_or_404(Document, slug=slug)
    if not doc.visible_to(request.user):
        raise Http404()
    if not doc.file:
        raise Http404()
    # FileResponse handles streaming + Content-Disposition.
    filename = doc.file.name.rsplit("/", 1)[-1]
    return FileResponse(doc.file.open("rb"), as_attachment=False, filename=filename)
