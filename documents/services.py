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

    # A revision's timestamp is when its state was *replaced*, so the note says
    # "in force until" — the history page names versions by their period, and
    # "saved <t>" would read as when that version began.
    when = timezone.localtime(revision.saved_at).strftime("%b %-d, %Y at %H:%M")
    document.snapshot_revision(
        user=user, note=f"Before restoring the version in force until {when}",
    )
    for name in SNAPSHOT_FIELDS:
        setattr(document, name, getattr(revision, name))
    document.file = revision.file.name or ""
    document.save()
    return document
