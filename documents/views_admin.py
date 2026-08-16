"""The Web Coordinator's document management surface (task #592).

Role-based, like every other admin area here: it lives under the Web
Coordinator admin rather than on the object's own public page, which also
keeps the revision history off the public template entirely.
"""

from __future__ import annotations

from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import DocumentEditForm
from .models import Document, DocumentRevision
from .permissions import manage_documents_required
from .services import restore_revision


def revision_rows(document: Document) -> list[dict]:
    """The history as a list of *versions*, newest first.

    A revision stores the state before one save, so it is the document as it
    stood **from the previous save until its own** — the oldest reaching back
    to the document's creation. Carrying that period is what lets the page say
    "this version" and have it mean the state the download and restore buttons
    act on: framed as an event ("on the 15th, X changed the summary"), the row's
    own buttons would be reaching for the state *before* the change described.

    ``changes`` still points away from the row — what changed when this version
    was replaced — which reads correctly under a "Replaced by" heading.
    """
    revisions = list(document.revisions.select_related("saved_by"))
    rows = []
    successor = document
    for index, rev in enumerate(revisions):
        older = revisions[index + 1] if index + 1 < len(revisions) else None
        start = older.saved_at if older else document.created_at
        rows.append({
            "revision": rev,
            "changes": rev.changes_against(successor),
            "in_force_from": start,
            "in_force_until": rev.saved_at,
            # Two saves a minute apart would render an identical range on both
            # ends — a likely sequence (upload the PDF, then fix a typo), and a
            # zero-width period reads as a bug rather than as a brief version.
            "brief": _same_minute(start, rev.saved_at),
        })
        successor = rev
    return rows


def _same_minute(a, b) -> bool:
    """Whether two instants render identically at the page's granularity."""
    fmt = "%Y-%m-%d %H:%M"
    return timezone.localtime(a).strftime(fmt) == timezone.localtime(b).strftime(fmt)


@manage_documents_required
def index(request):
    documents = (
        Document.objects.select_related("owning_workgroup")
        .order_by("category", "display_order", "title")
    )
    return render(request, "documents/admin/index.html", {
        "documents": documents,
    })


@manage_documents_required
def edit(request, slug: str):
    doc = get_object_or_404(Document, slug=slug)

    if request.method != "POST":
        form = DocumentEditForm(instance=doc)
    else:
        form = DocumentEditForm(request.POST, request.FILES, instance=doc)
        if form.is_valid():
            # Safe before or after binding — snapshot_revision re-reads the row.
            doc.snapshot_revision(
                user=request.user, note=form.cleaned_data.get("note", ""),
            )
            form.save()
            messages.success(
                request,
                "Document updated. The previous version is in its history.",
            )
            return redirect("documents_admin:edit", slug=doc.slug)

    rows = revision_rows(doc)
    return render(request, "documents/admin/edit.html", {
        "doc": doc, "form": form, "rows": rows,
        # The live version has been in force since the last save — or since the
        # document was created, if it has never been edited.
        "current_since": rows[0]["in_force_until"] if rows else doc.created_at,
    })


@manage_documents_required
def current_download(request, slug: str):
    """The live PDF, on this surface's own gate.

    Not a link to ``documents:download``: that one gates on
    ``is_lsp_member``, which a Web Coordinator need not be, so a members-only
    document would bounce the very person managing it.
    """
    doc = get_object_or_404(Document, slug=slug)
    if not doc.file:
        raise Http404()
    name = doc.file.name.rsplit("/", 1)[-1]
    return FileResponse(doc.file.open("rb"), as_attachment=False, filename=name)


@manage_documents_required
def revision_download(request, slug: str, pk: int):
    revision = get_object_or_404(DocumentRevision, pk=pk, document__slug=slug)
    if not revision.file:
        raise Http404()
    name = revision.file.name.rsplit("/", 1)[-1]
    return FileResponse(revision.file.open("rb"), as_attachment=False,
                        filename=name)


@require_POST
@manage_documents_required
def restore(request, slug: str, pk: int):
    doc = get_object_or_404(Document, slug=slug)
    revision = get_object_or_404(DocumentRevision, pk=pk, document=doc)
    restore_revision(doc, revision, user=request.user)
    messages.success(
        request,
        "Restored. The version you replaced is still in the history.",
    )
    return redirect("documents_admin:edit", slug=doc.slug)
