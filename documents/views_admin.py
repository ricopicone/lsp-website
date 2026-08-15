"""The Web Coordinator's document management surface (task #592).

Role-based, like every other admin area here: it lives under the Web
Coordinator admin rather than on the object's own public page, which also
keeps the revision history off the public template entirely.
"""

from __future__ import annotations

from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import DocumentEditForm
from .models import Document, DocumentRevision
from .permissions import manage_documents_required
from .services import restore_revision


def revision_rows(document: Document) -> list[dict]:
    """Each revision paired with what changed between it and the state that
    followed — the next revision, or the live document for the newest."""
    rows = []
    successor = document
    for rev in document.revisions.select_related("saved_by"):
        rows.append({"revision": rev, "changes": rev.changes_against(successor)})
        successor = rev
    return rows


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

    return render(request, "documents/admin/edit.html", {
        "doc": doc, "form": form, "rows": revision_rows(doc),
    })


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
