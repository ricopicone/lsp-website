"""Documents app views.

The index renders the (current) Document list grouped by category as
cards. Detail pages show the longer markdown description, author
byline, and a download link gated by ``content_visible_to``. Two-axis
visibility means a document can be browsable to the public while its
PDF stays members-only.
"""

from __future__ import annotations

from django.db.models import Prefetch
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render

from .models import Document, DocumentAuthor


def _with_authors(qs):
    """Prefetch authorships in byline order and the owning workgroup."""
    return qs.select_related("owning_workgroup").prefetch_related(
        Prefetch(
            "authorships",
            queryset=(
                DocumentAuthor.objects
                .select_related("user")
                .order_by("display_order")
            ),
        ),
    )


def index(request):
    qs = _with_authors(
        Document.for_user(request.user).order_by("category", "display_order", "title")
    )

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
    doc = get_object_or_404(_with_authors(Document.objects.all()), slug=slug)
    if not doc.listing_visible_to(request.user):
        raise Http404()
    older = (
        doc.supersedes.all().order_by("-effective_date")
        if doc.is_current
        else []
    )
    return render(
        request,
        "documents/detail.html",
        {
            "doc": doc,
            "older_versions": older,
            "content_visible": doc.content_visible_to(request.user),
        },
    )


def download(request, slug):
    doc = get_object_or_404(Document, slug=slug)
    if not doc.content_visible_to(request.user):
        raise Http404()
    if not doc.file:
        raise Http404()
    filename = doc.file.name.rsplit("/", 1)[-1]
    return FileResponse(doc.file.open("rb"), as_attachment=False, filename=filename)
