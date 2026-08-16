"""Document management side-effects shared by the admin surface (task #592)."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import SNAPSHOT_FIELDS, Document, DocumentRevision


@transaction.atomic
def restore_revision(
    document: Document, revision: DocumentRevision, user=None,
) -> Document:
    """Put ``revision``'s state back onto ``document``.

    Forward-only: the current state is snapshotted first, so restoring is
    itself an edit in the history and nothing is ever destroyed.
    """
    if revision.document_id != document.pk:
        raise ValueError("That revision belongs to a different document.")

    when = timezone.localtime(revision.saved_at).strftime("%b %-d, %Y at %H:%M")
    document.snapshot_revision(
        user=user, note=f"Before restoring the version saved {when}",
    )
    for name in SNAPSHOT_FIELDS:
        setattr(document, name, getattr(revision, name))
    document.file = revision.file.name or ""
    document.save()
    return document
