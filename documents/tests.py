"""Tests for documents app — visibility gating, authors, notice, version chain."""

from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.models import Profile, User
from documents.models import Document, DocumentAuthor


def _doc(**kwargs) -> Document:
    """Build a Document with sensible defaults + a tiny stub PDF."""
    defaults = dict(
        title="Test doc",
        slug="test-doc",
        category=Document.Category.GOVERNANCE,
        summary="A test document",
        listing_visibility=Document.Visibility.PUBLIC,
        content_visibility=Document.Visibility.PUBLIC,
        file=SimpleUploadedFile(
            "test.pdf", b"%PDF-1.4\n%fake\n", content_type="application/pdf",
        ),
    )
    defaults.update(kwargs)
    return Document.objects.create(**defaults)


# ---- Two-axis visibility ------------------------------------------------


@pytest.mark.django_db
def test_listing_visible_to_anon_when_listing_public():
    d = _doc()
    assert d.listing_visible_to(None) is True


@pytest.mark.django_db
def test_listing_hidden_from_anon_when_listing_members():
    d = _doc(listing_visibility=Document.Visibility.MEMBERS)
    assert d.listing_visible_to(None) is False


@pytest.mark.django_db
def test_public_listing_with_members_pdf_visible_listing_gated_pdf():
    """The headline scenario: anon sees the listing, can't download the PDF."""
    d = _doc(
        listing_visibility=Document.Visibility.PUBLIC,
        content_visibility=Document.Visibility.MEMBERS,
    )
    assert d.listing_visible_to(None) is True
    assert d.content_visible_to(None) is False
    member = User.objects.create_user(email="m@x.test")
    member.profile.role = Profile.Role.ANALYST
    member.profile.save(update_fields=["role"])
    assert d.content_visible_to(member) is True
    # An auditor (outside registrant, default role=external) is not a member.
    auditor = User.objects.create_user(email="a@x.test")
    assert d.content_visible_to(auditor) is False


@pytest.mark.django_db
def test_clean_rejects_public_pdf_with_members_listing():
    d = Document(
        title="X", slug="x", category=Document.Category.GOVERNANCE,
        listing_visibility=Document.Visibility.MEMBERS,
        content_visibility=Document.Visibility.PUBLIC,
        file=SimpleUploadedFile("t.pdf", b"%PDF", content_type="application/pdf"),
    )
    with pytest.raises(ValidationError) as exc:
        d.full_clean()
    assert "content_visibility" in exc.value.error_dict


# ---- for_user filter ---------------------------------------------------


@pytest.mark.django_db
def test_for_user_anon_only_sees_public_listings():
    _doc(slug="open")
    _doc(slug="closed", listing_visibility=Document.Visibility.MEMBERS)
    slugs = set(Document.for_user(None).values_list("slug", flat=True))
    assert slugs == {"open"}


@pytest.mark.django_db
def test_for_user_member_sees_all_listings():
    _doc(slug="open")
    _doc(slug="closed", listing_visibility=Document.Visibility.MEMBERS)
    u = User.objects.create_user(email="m@x.test")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save(update_fields=["role"])
    slugs = set(Document.for_user(u).values_list("slug", flat=True))
    assert slugs == {"open", "closed"}


@pytest.mark.django_db
def test_for_user_auditor_only_sees_public_listings():
    """An authenticated outside registrant (auditor, role=external) is not a
    member and must not see members-only listings."""
    _doc(slug="open")
    _doc(slug="closed", listing_visibility=Document.Visibility.MEMBERS)
    u = User.objects.create_user(email="ext@x.test")  # default role = external
    slugs = set(Document.for_user(u).values_list("slug", flat=True))
    assert slugs == {"open"}


@pytest.mark.django_db
def test_for_user_excludes_superseded():
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
    body = client.get(reverse("documents:index")).content.decode()
    assert body.index("Governance one") < body.index("Formation one") < body.index("Reference one")


@pytest.mark.django_db
def test_index_excludes_members_only_listings_for_anonymous(client):
    _doc(slug="open", title="Open one")
    _doc(slug="secret", title="Secret one", listing_visibility=Document.Visibility.MEMBERS)
    body = client.get(reverse("documents:index")).content.decode()
    assert "Open one" in body
    assert "Secret one" not in body


@pytest.mark.django_db
def test_index_shows_public_listing_with_members_pdf_to_anon(client):
    """The headline scenario rendered: anon sees the entry but no download access."""
    _doc(
        slug="founding",
        title="Founding Paper",
        content_visibility=Document.Visibility.MEMBERS,
    )
    body = client.get(reverse("documents:index")).content.decode()
    assert "Founding Paper" in body
    assert "Contents: Members only" in body


@pytest.mark.django_db
def test_detail_404s_for_anonymous_on_members_only_listing(client):
    _doc(slug="secret", listing_visibility=Document.Visibility.MEMBERS)
    resp = client.get(reverse("documents:detail", args=["secret"]))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_detail_renders_for_anon_when_listing_public_but_pdf_members(client):
    _doc(
        slug="founding",
        title="Founding Paper",
        content_visibility=Document.Visibility.MEMBERS,
    )
    body = client.get(reverse("documents:detail", args=["founding"])).content.decode()
    assert "Founding Paper" in body
    assert "Log in to download PDF" in body
    # The live download button should not appear for anon when PDF is members-only.
    assert reverse("documents:download", args=["founding"]) not in body


@pytest.mark.django_db
def test_detail_shows_download_for_member_on_members_pdf(client):
    _doc(slug="founding", content_visibility=Document.Visibility.MEMBERS)
    u = User.objects.create_user(email="m@x.test", password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save(update_fields=["role"])
    client.force_login(u)
    body = client.get(reverse("documents:detail", args=["founding"])).content.decode()
    assert reverse("documents:download", args=["founding"]) in body
    assert "Download PDF" in body


@pytest.mark.django_db
def test_download_404s_for_auditor_on_members_pdf(client):
    """A logged-in auditor (outside registrant) cannot download members-only."""
    _doc(slug="founding", content_visibility=Document.Visibility.MEMBERS)
    u = User.objects.create_user(email="ext@x.test", password="x")  # role=external
    client.force_login(u)
    resp = client.get(reverse("documents:download", args=["founding"]))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_download_serves_file_for_public_pdf_anon(client):
    _doc(slug="open")
    resp = client.get(reverse("documents:download", args=["open"]))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_download_404s_for_anonymous_on_members_pdf(client):
    _doc(slug="founding", content_visibility=Document.Visibility.MEMBERS)
    resp = client.get(reverse("documents:download", args=["founding"]))
    assert resp.status_code == 404


# ---- Authors -----------------------------------------------------------


@pytest.mark.django_db
def test_detail_renders_linked_authors(client):
    u = User.objects.create_user(
        email="a@x.test", password="x", first_name="Andre", last_name="Patsalides",
    )
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    d = _doc(slug="founding", title="Founding Paper")
    DocumentAuthor.objects.create(document=d, user=u, display_order=0)
    body = client.get(reverse("documents:detail", args=["founding"])).content.decode()
    assert "Andre Patsalides" in body
    # Linked to the directory profile.
    assert f'href="/directory/{u.profile.directory_slug}/"' in body


@pytest.mark.django_db
def test_index_card_renders_linked_authors(client):
    u = User.objects.create_user(
        email="a@x.test", password="x", first_name="Andre", last_name="Patsalides",
    )
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    d = _doc(slug="founding", title="Founding Paper")
    DocumentAuthor.objects.create(document=d, user=u, display_order=0)
    body = client.get(reverse("documents:index")).content.decode()
    assert "Andre Patsalides" in body


# ---- Notice ------------------------------------------------------------


@pytest.mark.django_db
def test_detail_shows_notice_banner(client):
    _doc(slug="sg", notice="Under revision — procedural details may change")
    body = client.get(reverse("documents:detail", args=["sg"])).content.decode()
    assert "Under revision" in body


@pytest.mark.django_db
def test_index_card_shows_notice_chip(client):
    _doc(slug="sg", notice="Under revision")
    body = client.get(reverse("documents:index")).content.decode()
    assert "Under revision" in body


# ---- Versioning --------------------------------------------------------


@pytest.mark.django_db
def test_detail_lists_older_versions(client):
    new = _doc(slug="bylaws-2024", title="Bylaws 2024", effective_date=date(2024, 12, 1))
    _doc(
        slug="bylaws-2022", title="Bylaws 2022",
        effective_date=date(2022, 1, 1), superseded_by=new,
    )
    body = client.get(reverse("documents:detail", args=["bylaws-2024"])).content.decode()
    assert "Bylaws 2022" in body
    assert "Earlier versions" in body


# ---- Ownership (produced by a committee / working group) ----------------


@pytest.mark.django_db
def test_owning_workgroup_links_document_to_its_producing_group():
    from committees.models import Committee

    pc = Committee.objects.get(name="Program Committee")  # seeded by migrations
    d = _doc(slug="pp-style", title="Program Proposal Style Guide",
             owning_workgroup=pc.workgroup)
    # The relation reads both ways: the document knows its owner, and the
    # group lists what it produced.
    assert d.owning_workgroup == pc.workgroup
    assert list(pc.workgroup.documents.all()) == [d]


@pytest.mark.django_db
def test_owning_group_survives_workgroup_deletion():
    """SET_NULL keeps the document if its owning group is removed."""
    from workgroups.models import Workgroup

    wg = Workgroup.objects.create(kind=Workgroup.Kind.WORKING_GROUP, name="WG", slug="wg")
    d = _doc(slug="owned", owning_workgroup=wg)
    wg.delete()
    d.refresh_from_db()
    assert d.owning_workgroup_id is None


@pytest.mark.django_db
def test_index_card_shows_owning_group(client):
    from committees.models import Committee

    pc = Committee.objects.get(name="Program Committee")  # seeded by migrations
    _doc(slug="pp-style", category=Document.Category.REFERENCE,
         owning_workgroup=pc.workgroup)
    body = client.get(reverse("documents:index")).content.decode()
    assert "A product of the Program Committee" in body
