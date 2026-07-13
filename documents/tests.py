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
def test_detail_redirects_anonymous_to_login_on_members_only_listing(client):
    _doc(slug="secret", listing_visibility=Document.Visibility.MEMBERS)
    url = reverse("documents:detail", args=["secret"])
    resp = client.get(url)
    assert resp.status_code == 302
    assert resp.url == f"/accounts/login/?next={url}"


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
def test_download_redirects_anonymous_to_login_on_members_pdf(client):
    _doc(slug="founding", content_visibility=Document.Visibility.MEMBERS)
    url = reverse("documents:download", args=["founding"])
    resp = client.get(url)
    assert resp.status_code == 302
    assert resp.url == f"/accounts/login/?next={url}"


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


# ---- Inline HTML body (PDF-free documents) -----------------------------


def _html_doc(**kwargs) -> Document:
    """A body-only Document — HTML content, no PDF file."""
    defaults = dict(
        title="HTML doc",
        slug="html-doc",
        category=Document.Category.REFERENCE,
        summary="An HTML document",
        listing_visibility=Document.Visibility.PUBLIC,
        content_visibility=Document.Visibility.PUBLIC,
        file="",
        body="## Heading\n\nA paragraph.",
    )
    defaults.update(kwargs)
    return Document.objects.create(**defaults)


def _current_tuition_period(amount):
    from payments.models import TuitionPeriod

    return TuitionPeriod.objects.create(
        name="AY 2026–2027",
        slug="ay-2026-2027",
        start_date=date(2026, 7, 1),
        decision_due_date=date(2026, 9, 15),
        end_date=date(2027, 6, 30),
        tuition_amount=amount,
    )


@pytest.mark.django_db
def test_body_html_renders_markdown():
    d = _html_doc(body="## Tuition\n\nPay in **September**.")
    html = d.body_html
    assert "<h2" in html
    assert "<strong>September</strong>" in html


@pytest.mark.django_db
def test_render_body_substitutes_annual_tuition_token():
    import documents.rendering as rendering

    _current_tuition_period(2500)
    html = rendering.render_body(
        "Pay a total of {{ annual_tuition }} for the year.",
        on_date=date(2026, 10, 1),
    )
    assert "$2,500" in html
    assert "{{ annual_tuition }}" not in html


@pytest.mark.django_db
def test_annual_tuition_reads_current_period():
    import documents.rendering as rendering

    _current_tuition_period(2500)
    assert rendering.annual_tuition(on_date=date(2026, 10, 1)) == "$2,500"


@pytest.mark.django_db
def test_annual_tuition_falls_back_without_period():
    import documents.rendering as rendering
    from payments.models import TuitionPeriod

    TuitionPeriod.objects.all().delete()
    assert rendering.annual_tuition() == "the annual tuition amount"


@pytest.mark.django_db
def test_clean_allows_body_only_document():
    d = Document(
        title="Body only", slug="body-only",
        category=Document.Category.REFERENCE,
        listing_visibility=Document.Visibility.PUBLIC,
        content_visibility=Document.Visibility.PUBLIC,
        file="",
        body="Some content.",
    )
    d.full_clean()  # should not raise


@pytest.mark.django_db
def test_clean_rejects_document_with_neither_file_nor_body():
    d = Document(
        title="Empty", slug="empty",
        category=Document.Category.REFERENCE,
        listing_visibility=Document.Visibility.PUBLIC,
        content_visibility=Document.Visibility.PUBLIC,
        file="",
        body="",
    )
    with pytest.raises(ValidationError):
        d.full_clean()


@pytest.mark.django_db
def test_detail_renders_body_inline_for_public_body_doc(client):
    _html_doc(slug="tuition-assistance", title="Tuition Assistance",
              body="## Assistance\n\nContact **the Treasurer**.")
    body = client.get(reverse("documents:detail", args=["tuition-assistance"])).content.decode()
    assert "Contact <strong>the Treasurer</strong>" in body
    # No PDF, so no download button.
    assert reverse("documents:download", args=["tuition-assistance"]) not in body
    assert "Download PDF" not in body


@pytest.mark.django_db
def test_detail_body_gated_for_anon_when_members(client):
    _html_doc(slug="members-body", title="Members Body",
              listing_visibility=Document.Visibility.PUBLIC,
              content_visibility=Document.Visibility.MEMBERS,
              body="Secret **members-only** text here.")
    body = client.get(reverse("documents:detail", args=["members-body"])).content.decode()
    assert "Members Body" in body
    assert "members-only" not in body
    assert "Log in to read" in body


@pytest.mark.django_db
def test_index_card_shows_view_for_body_only_doc(client):
    _html_doc(slug="tuition-assistance", title="Tuition Assistance")
    body = client.get(reverse("documents:index")).content.decode()
    detail_url = reverse("documents:detail", args=["tuition-assistance"])
    # The primary card action is a "View" button linking to the detail page.
    assert f'href="{detail_url}"' in body
    assert "View" in body
    # A body-only doc has no download link on its card.
    assert reverse("documents:download", args=["tuition-assistance"]) not in body


@pytest.mark.django_db
def test_detail_body_uses_lsp_prose(client):
    """Inline bodies render in .lsp-prose (the project's real prose styling),
    not bare .prose (which this project has no plugin for)."""
    _html_doc(slug="hp", body="A paragraph.\n\nAnother paragraph.")
    body = client.get(reverse("documents:detail", args=["hp"])).content.decode()
    assert "lsp-prose" in body


@pytest.mark.django_db
def test_shipped_tuition_body_v2_is_clean_linked_and_covers_skipping():
    """The reworked Tuition Assistance content: no stale names, live figure,
    links to the My LSP Tuition page and the Treasurer, and the skip decision."""
    import importlib

    from documents.rendering import render_body

    mod = importlib.import_module(
        "documents.migrations.0010_drop_yearend_reconciliation_sentence"
    )
    _current_tuition_period(2500)
    html = render_body(mod.BODY, on_date=date(2026, 10, 1))
    assert "Scalia" not in html
    assert "Carlson" not in html
    # The year-end reconciliation sentence (and its dollar figure) was removed;
    # the reminder/escalation follow-up stays.
    assert "full annual amount" not in html
    assert "$2,500" not in html
    assert "$2,000" not in html
    assert "raises the matter with the Board" in html
    # "written" dropped from the student's own record-keeping phrasing.
    assert "written" not in html.lower()
    assert 'href="/formation/?tab=tuition"' in html
    assert 'href="mailto:treasurer@lacanschool.org"' in html
    assert "skip" in html.lower()


@pytest.mark.django_db
def test_shipped_tuition_body_is_clean_and_current():
    """The converted Tuition Assistance content carries no stale names/figures
    and renders the live tuition figure via the {{ annual_tuition }} token."""
    import importlib

    from documents.rendering import render_body

    mod = importlib.import_module(
        "documents.migrations.0008_convert_tuition_assistance_to_html"
    )
    _current_tuition_period(2500)
    html = render_body(mod.BODY, on_date=date(2026, 10, 1))
    assert "Scalia" not in html
    assert "Carlson de la Torre" not in html
    assert "lacanschool.com" not in html
    assert "$2,000" not in html
    assert "$2,500" in html
    assert "/tuition/" in html
