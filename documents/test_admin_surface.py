"""Tests for the Web Coordinator's document management surface (task #592)."""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.models import Profile, User
from core.models import StaffRole
from documents.models import Document


def _doc(**kwargs) -> Document:
    defaults = dict(
        title="Test doc", slug="test-doc",
        category=Document.Category.FORMATION,
        summary="A test document",
        file=SimpleUploadedFile("old.pdf", b"%PDF-1.4\nold\n",
                                content_type="application/pdf"),
    )
    defaults.update(kwargs)
    return Document.objects.create(**defaults)


def _user(email="u@x.test", role=Profile.Role.ANALYST) -> User:
    u = User.objects.create_user(email=email)
    u.profile.role = role
    u.profile.save(update_fields=["role"])
    return u


def _coordinator(email="wc@x.test") -> User:
    u = _user(email)
    StaffRole.objects.get_or_create(
        key=StaffRole.WEB_COORDINATOR, defaults={"name": "Web Coordinator"},
    )[0].holders.add(u)
    return u


# ---- The gate -----------------------------------------------------------


@pytest.mark.django_db
def test_can_manage_rejects_anonymous():
    from documents.permissions import can_manage_documents
    assert can_manage_documents(None) is False


@pytest.mark.django_db
def test_can_manage_rejects_plain_member():
    from documents.permissions import can_manage_documents
    assert can_manage_documents(_user()) is False


@pytest.mark.django_db
def test_can_manage_allows_web_coordinator():
    from documents.permissions import can_manage_documents
    assert can_manage_documents(_coordinator()) is True


@pytest.mark.django_db
def test_can_manage_allows_superuser():
    from documents.permissions import can_manage_documents
    u = User.objects.create_superuser(email="su@x.test", password="x")
    assert can_manage_documents(u) is True


@pytest.mark.django_db
def test_can_manage_rejects_web_developer():
    """The Web Developer holds the Django admin path, not this surface."""
    from documents.permissions import can_manage_documents
    u = _user("wd@x.test")
    StaffRole.objects.get_or_create(
        key=StaffRole.WEB_DEVELOPER, defaults={"name": "Web Developer"},
    )[0].holders.add(u)
    assert can_manage_documents(u) is False


# ---- The form -----------------------------------------------------------


@pytest.mark.django_db
def test_form_display_order_is_optional():
    """A model field with a default but no blank=True lands on a ModelForm as
    REQUIRED unless told otherwise (new-modelform-field-is-required-by-default)."""
    from documents.forms import DocumentEditForm
    d = _doc()
    form = DocumentEditForm(
        {"title": "T", "listing_visibility": "public",
         "content_visibility": "public", "body": "text"},
        instance=d,
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["display_order"] == 0


@pytest.mark.django_db
def test_form_rejects_public_contents_under_members_listing():
    from documents.forms import DocumentEditForm
    d = _doc()
    form = DocumentEditForm(
        {"title": "T", "listing_visibility": "members",
         "content_visibility": "public", "display_order": 0},
        instance=d,
    )
    assert not form.is_valid()
    assert "content_visibility" in form.errors


@pytest.mark.django_db
def test_form_keeps_the_existing_file_when_none_uploaded():
    from documents.forms import DocumentEditForm
    d = _doc()
    original = d.file.name
    form = DocumentEditForm(
        {"title": "Renamed", "listing_visibility": "public",
         "content_visibility": "public", "display_order": 0},
        instance=d,
    )
    assert form.is_valid(), form.errors
    assert form.save().file.name == original


# ---- The management views ----------------------------------------------


@pytest.mark.django_db
def test_index_redirects_anonymous_to_login(client):
    _doc()
    resp = client.get(reverse("documents_admin:index"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@pytest.mark.django_db
def test_index_forbidden_for_plain_member(client):
    _doc()
    client.force_login(_user())
    assert client.get(reverse("documents_admin:index")).status_code == 403


@pytest.mark.django_db
def test_index_lists_documents_for_the_coordinator(client):
    _doc(title="Scholar Formation Guidelines")
    client.force_login(_coordinator())
    resp = client.get(reverse("documents_admin:index"))
    assert resp.status_code == 200
    assert b"Scholar Formation Guidelines" in resp.content


@pytest.mark.django_db
def test_edit_replaces_the_file_and_writes_a_revision(client):
    d = _doc()
    original = d.file.name
    client.force_login(_coordinator())
    resp = client.post(
        reverse("documents_admin:edit", args=[d.slug]),
        {
            "title": d.title, "summary": d.summary, "description": "",
            "notice": "", "body": "", "effective_date": "2026-08-15",
            "listing_visibility": "public", "content_visibility": "public",
            "display_order": 10, "note": "New board copy",
            "file": SimpleUploadedFile("new.pdf", b"%PDF-1.4\nnew\n",
                                       content_type="application/pdf"),
        },
    )
    assert resp.status_code == 302
    d.refresh_from_db()
    assert d.file.name != original
    assert str(d.effective_date) == "2026-08-15"
    rev = d.revisions.get()
    assert rev.file.name == original
    assert rev.note == "New board copy"


@pytest.mark.django_db
def test_edit_writes_a_revision_for_a_metadata_only_change(client):
    d = _doc(title="Old")
    client.force_login(_coordinator())
    client.post(
        reverse("documents_admin:edit", args=[d.slug]),
        {"title": "New", "summary": "", "description": "", "notice": "",
         "body": "", "effective_date": "", "listing_visibility": "public",
         "content_visibility": "public", "display_order": 0, "note": ""},
    )
    d.refresh_from_db()
    assert d.title == "New"
    assert d.revisions.get().title == "Old"


@pytest.mark.django_db
def test_restore_view_puts_the_old_version_back(client):
    d = _doc(title="Original")
    client.force_login(_coordinator())
    client.post(
        reverse("documents_admin:edit", args=[d.slug]),
        {"title": "Replaced", "summary": "", "description": "", "notice": "",
         "body": "", "effective_date": "", "listing_visibility": "public",
         "content_visibility": "public", "display_order": 0, "note": ""},
    )
    d.refresh_from_db()
    assert d.title == "Replaced"
    rev = d.revisions.get()
    resp = client.post(reverse("documents_admin:restore", args=[d.slug, rev.pk]))
    assert resp.status_code == 302
    d.refresh_from_db()
    assert d.title == "Original"
    assert d.revisions.count() == 2


@pytest.mark.django_db
def test_revision_download_is_gated(client):
    d = _doc()
    rev = d.snapshot_revision()
    url = reverse("documents_admin:revision_download", args=[d.slug, rev.pk])
    client.force_login(_user())
    assert client.get(url).status_code == 403


@pytest.mark.django_db
def test_revision_download_serves_the_old_pdf(client):
    d = _doc()
    rev = d.snapshot_revision()
    client.force_login(_coordinator())
    resp = client.get(
        reverse("documents_admin:revision_download", args=[d.slug, rev.pk])
    )
    assert resp.status_code == 200
    assert b"%PDF" in b"".join(resp.streaming_content)
