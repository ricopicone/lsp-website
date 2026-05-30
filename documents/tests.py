"""Tests for documents app — visibility gating, version chain, index grouping."""

from __future__ import annotations

from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.models import User
from documents.models import Document


def _doc(**kwargs) -> Document:
    """Build a Document with sensible defaults + a tiny stub PDF."""
    defaults = dict(
        title="Test doc",
        slug="test-doc",
        category=Document.Category.GOVERNANCE,
        summary="A test document",
        visibility=Document.Visibility.PUBLIC,
        file=SimpleUploadedFile("test.pdf", b"%PDF-1.4\n%fake\n", content_type="application/pdf"),
    )
    defaults.update(kwargs)
    return Document.objects.create(**defaults)


# ---- for_user / visible_to ---------------------------------------------


@pytest.mark.django_db
def test_for_user_anonymous_only_sees_public():
    _doc(slug="open", visibility=Document.Visibility.PUBLIC)
    _doc(slug="closed", visibility=Document.Visibility.MEMBERS)

    qs = Document.for_user(None)  # anonymous
    slugs = set(qs.values_list("slug", flat=True))
    assert slugs == {"open"}


@pytest.mark.django_db
def test_for_user_authenticated_sees_both():
    _doc(slug="open", visibility=Document.Visibility.PUBLIC)
    _doc(slug="closed", visibility=Document.Visibility.MEMBERS)
    u = User.objects.create_user(email="m@x.test")

    qs = Document.for_user(u)
    slugs = set(qs.values_list("slug", flat=True))
    assert slugs == {"open", "closed"}


@pytest.mark.django_db
def test_for_user_excludes_superseded():
    """Superseded docs don't appear in for_user even when current."""
    new = _doc(slug="bylaws-2024", title="Bylaws 2024", effective_date=date(2024, 12, 1))
    old = _doc(slug="bylaws-2022", title="Bylaws 2022", effective_date=date(2022, 1, 1))
    old.superseded_by = new
    old.save()

    slugs = set(Document.for_user(None).values_list("slug", flat=True))
    assert slugs == {"bylaws-2024"}


# ---- Views: index + detail + download ----------------------------------


@pytest.mark.django_db
def test_index_renders_groups_in_category_order(client):
    _doc(slug="g1", title="Governance one", category=Document.Category.GOVERNANCE)
    _doc(slug="r1", title="Reference one", category=Document.Category.REFERENCE)
    _doc(slug="f1", title="Formation one", category=Document.Category.FORMATION)

    resp = client.get(reverse("documents:index"))
    body = resp.content.decode()
    assert resp.status_code == 200
    # Governance should appear before Formation before Reference in the
    # rendered HTML (matches Document.CATEGORY_ORDER).
    g = body.index("Governance one")
    f = body.index("Formation one")
    r = body.index("Reference one")
    assert g < f < r


@pytest.mark.django_db
def test_index_excludes_members_only_for_anonymous(client):
    _doc(slug="open", title="Open one", visibility=Document.Visibility.PUBLIC)
    _doc(slug="secret", title="Secret one", visibility=Document.Visibility.MEMBERS)

    body = client.get(reverse("documents:index")).content.decode()
    assert "Open one" in body
    assert "Secret one" not in body


@pytest.mark.django_db
def test_detail_404s_for_anonymous_on_members_only(client):
    _doc(slug="secret", visibility=Document.Visibility.MEMBERS)
    resp = client.get(reverse("documents:detail", args=["secret"]))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_detail_renders_for_member_on_members_only(client):
    _doc(slug="secret", visibility=Document.Visibility.MEMBERS, title="Secret memo")
    u = User.objects.create_user(email="m@x.test", password="x")
    client.force_login(u)
    resp = client.get(reverse("documents:detail", args=["secret"]))
    assert resp.status_code == 200
    assert "Secret memo" in resp.content.decode()


@pytest.mark.django_db
def test_detail_lists_older_versions(client):
    new = _doc(slug="bylaws-2024", title="Bylaws 2024", effective_date=date(2024, 12, 1))
    _doc(  # old version, points at new
        slug="bylaws-2022",
        title="Bylaws 2022",
        effective_date=date(2022, 1, 1),
        superseded_by=new,
    )
    body = client.get(reverse("documents:detail", args=["bylaws-2024"])).content.decode()
    assert "Bylaws 2022" in body
    assert "Earlier versions" in body


@pytest.mark.django_db
def test_download_serves_file_for_public_anonymous(client):
    _doc(slug="open")
    resp = client.get(reverse("documents:download", args=["open"]))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_download_404s_for_anonymous_on_members_only(client):
    _doc(slug="secret", visibility=Document.Visibility.MEMBERS)
    resp = client.get(reverse("documents:download", args=["secret"]))
    assert resp.status_code == 404
