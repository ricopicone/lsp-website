"""Revision snapshots for documents (task #592)."""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import User
from documents.models import Document, DocumentRevision

from .test_admin_surface import _doc


@pytest.mark.django_db
def test_snapshot_captures_current_state():
    d = _doc(title="Before")
    rev = d.snapshot_revision(note="why")
    assert rev.title == "Before"
    assert rev.document_id == d.pk
    assert rev.note == "why"
    assert rev.file.name == d.file.name


@pytest.mark.django_db
def test_snapshot_records_who():
    d = _doc()
    u = User.objects.create_user(email="who@x.test")
    assert d.snapshot_revision(user=u).saved_by_id == u.pk


@pytest.mark.django_db
def test_snapshot_ignores_in_place_mutation():
    """A ModelForm mutates its instance during validation (#532), so the
    snapshot must read the database, not the object handed to it."""
    d = _doc(title="Stored")
    d.title = "Mutated in memory"
    rev = d.snapshot_revision()
    assert rev.title == "Stored"


@pytest.mark.django_db
def test_changes_against_reports_differing_fields():
    d = _doc(title="Old title", summary="Old summary")
    rev = d.snapshot_revision()
    d.title = "New title"
    d.save(update_fields=["title"])
    changes = rev.changes_against(d)
    assert [c["field"] for c in changes] == ["title"]
    assert changes[0]["old"] == "Old title"
    assert changes[0]["new"] == "New title"
    assert changes[0]["label"]


@pytest.mark.django_db
def test_changes_against_reports_a_replaced_file():
    d = _doc()
    rev = d.snapshot_revision()
    d.file = SimpleUploadedFile("new.pdf", b"%PDF-1.4\nnew\n",
                                content_type="application/pdf")
    d.save()
    assert [c["field"] for c in rev.changes_against(d)] == ["file"]


@pytest.mark.django_db
def test_revisions_are_newest_first():
    d = _doc()
    first = d.snapshot_revision(note="first")
    second = d.snapshot_revision(note="second")
    assert list(d.revisions.all()) == [second, first]


@pytest.mark.django_db
def test_revision_file_points_at_the_same_object():
    """Snapshots reference the stored key; they never copy the file."""
    d = _doc()
    rev = d.snapshot_revision()
    assert rev.file.name == d.file.name
    assert DocumentRevision.objects.count() == 1


# ---- Restore ------------------------------------------------------------


@pytest.mark.django_db
def test_restore_puts_prior_values_back():
    from documents.services import restore_revision
    d = _doc(title="Original", summary="Original summary")
    rev = d.snapshot_revision()
    d.title = "Replaced"
    d.summary = "Replaced summary"
    d.save()
    restore_revision(d, rev)
    d.refresh_from_db()
    assert d.title == "Original"
    assert d.summary == "Original summary"


@pytest.mark.django_db
def test_restore_puts_the_prior_file_back():
    from documents.services import restore_revision
    d = _doc()
    original_name = d.file.name
    rev = d.snapshot_revision()
    d.file = SimpleUploadedFile("new.pdf", b"%PDF-1.4\nnew\n",
                                content_type="application/pdf")
    d.save()
    assert d.file.name != original_name
    restore_revision(d, rev)
    d.refresh_from_db()
    assert d.file.name == original_name


@pytest.mark.django_db
def test_restore_is_forward_only():
    """Restoring is itself an edit: the pre-restore state becomes a revision."""
    from documents.services import restore_revision
    d = _doc(title="Original")
    rev = d.snapshot_revision()
    d.title = "Replaced"
    d.save()
    restore_revision(d, rev)
    assert d.revisions.count() == 2
    assert d.revisions.first().title == "Replaced"


@pytest.mark.django_db
def test_restore_refuses_a_revision_from_another_document():
    from documents.services import restore_revision
    a = _doc(slug="doc-a")
    b = _doc(slug="doc-b", title="B")
    rev = b.snapshot_revision()
    with pytest.raises(ValueError):
        restore_revision(a, rev)
