"""Tests for the Web Coordinator's document management surface (task #592)."""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

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
