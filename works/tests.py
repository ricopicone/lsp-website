"""Tests for works app — visibility, permissions, multi-file form, tone-card hash."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.models import Profile, User
from works.forms import WorkForm
from works.models import Work, WorkAuthor, WorkFile
from works.templatetags.works_filters import PALETTE, tone_for


def _make_user(email="m@x.test", first="Mara", last="Smith", role=Profile.Role.MEMBER):
    u = User.objects.create_user(email=email, password="x", first_name=first, last_name=last)
    u.profile.role = role
    u.profile.save()
    return u


def _make_work(
    title="A Work", slug="a-work",
    listing=Work.Visibility.PUBLIC, pdf_vis=Work.Visibility.MEMBERS,
    files=None, kind=Work.Kind.EXTERNAL, submitted_by=None,
):
    w = Work.objects.create(
        title=title, slug=slug, kind=kind,
        listing_visibility=listing, pdf_visibility=pdf_vis,
        submitted_by=submitted_by,
    )
    if files:
        for i, (label, file_obj) in enumerate(files):
            WorkFile.objects.create(work=w, file=file_obj, label=label, display_order=i)
    return w


def _fake_pdf(name="x.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4\n%fake\n", content_type="application/pdf")


# ---- Visibility helpers ------------------------------------------------


@pytest.mark.django_db
def test_listing_visible_to_public_for_anonymous():
    w = _make_work(listing=Work.Visibility.PUBLIC)
    assert w.listing_visible_to(None) is True


@pytest.mark.django_db
def test_listing_hidden_from_anonymous_when_members_only():
    w = _make_work(listing=Work.Visibility.MEMBERS)
    assert w.listing_visible_to(None) is False


@pytest.mark.django_db
def test_pdf_visible_requires_at_least_one_file():
    """A work with no files reports pdf_visible_to=False regardless of visibility."""
    w = _make_work(pdf_vis=Work.Visibility.PUBLIC, files=None)
    assert w.pdf_visible_to(None) is False
    u = _make_user()
    assert w.pdf_visible_to(u) is False


@pytest.mark.django_db
def test_pdf_visible_to_anon_when_public_and_file_present():
    w = _make_work(
        pdf_vis=Work.Visibility.PUBLIC,
        files=[("", _fake_pdf())],
    )
    assert w.pdf_visible_to(None) is True


@pytest.mark.django_db
def test_pdf_members_only_blocks_anon_but_allows_member():
    w = _make_work(
        pdf_vis=Work.Visibility.MEMBERS,
        files=[("", _fake_pdf())],
    )
    assert w.pdf_visible_to(None) is False
    u = _make_user()
    assert w.pdf_visible_to(u) is True


@pytest.mark.django_db
def test_members_only_means_lsp_member_not_just_logged_in():
    """"Members only" tracks is_lsp_member, consistent with Workgroup —
    a logged-in non-member (prospective applicant / guest) doesn't qualify."""
    w = _make_work(listing=Work.Visibility.MEMBERS, slug="m-only")
    applicant = _make_user(email="hopeful@x.test", role=Profile.Role.PROSPECTIVE_APPLICANT)
    guest = _make_user(email="ext@x.test", role=Profile.Role.EXTERNAL)
    member = _make_user(email="real@x.test", role=Profile.Role.ANALYST)
    assert w.listing_visible_to(applicant) is False
    assert w.listing_visible_to(guest) is False
    assert w.listing_visible_to(member) is True
    assert w not in Work.listing_for(applicant)
    assert w in Work.listing_for(member)


# ---- Model.clean (visibility constraint) -------------------------------


@pytest.mark.django_db
def test_pdf_public_with_members_listing_invalid():
    w = Work(
        title="X", slug="x", kind=Work.Kind.EXTERNAL,
        listing_visibility=Work.Visibility.MEMBERS,
        pdf_visibility=Work.Visibility.PUBLIC,
    )
    with pytest.raises(ValidationError) as exc:
        w.full_clean()
    assert "pdf_visibility" in exc.value.error_dict


@pytest.mark.django_db
def test_group_visibility_requires_workgroup():
    w = Work(
        title="X", slug="x", kind=Work.Kind.CARTEL,
        listing_visibility=Work.Visibility.GROUP,
        pdf_visibility=Work.Visibility.GROUP,
    )
    with pytest.raises(ValidationError) as exc:
        w.full_clean()
    assert "workgroup" in exc.value.error_dict


# ---- GROUP (workgroup-only) visibility ---------------------------------


@pytest.mark.django_db
def test_group_work_visible_only_to_group_members():
    import datetime

    from workgroups.models import Workgroup, WorkgroupMembership

    wg = Workgroup.objects.create(kind=Workgroup.Kind.CARTEL, name="Cartel A")
    insider = _make_user(email="in@x.test")
    outsider = _make_user(email="out@x.test")
    WorkgroupMembership.objects.create(
        workgroup=wg, user=insider, start_date=datetime.date(2026, 1, 1)
    )
    w = _make_work(
        kind=Work.Kind.CARTEL,
        listing=Work.Visibility.GROUP,
        pdf_vis=Work.Visibility.GROUP,
    )
    w.workgroup = wg
    w.save()

    assert w.listing_visible_to(insider) is True
    assert w.listing_visible_to(outsider) is False
    assert w.listing_visible_to(None) is False
    # listing_for queryset agrees with the per-instance check
    assert w in Work.listing_for(insider)
    assert w not in Work.listing_for(outsider)
    assert w not in Work.listing_for(None)


# ---- editable_by -------------------------------------------------------


@pytest.mark.django_db
def test_editable_by_anon_is_false():
    w = _make_work()
    assert w.editable_by(None) is False


@pytest.mark.django_db
def test_editable_by_submitter_is_true():
    u = _make_user()
    w = _make_work(submitted_by=u)
    assert w.editable_by(u) is True


@pytest.mark.django_db
def test_editable_by_author_is_true():
    u = _make_user(email="author@x.test")
    submitter = _make_user(email="submitter@x.test")
    w = _make_work(submitted_by=submitter)
    WorkAuthor.objects.create(work=w, user=u, display_order=0)
    assert w.editable_by(u) is True


@pytest.mark.django_db
def test_editable_by_staff_is_true_even_when_unrelated():
    u = _make_user(email="staff@x.test")
    u.is_staff = True
    u.save()
    submitter = _make_user(email="s@x.test")
    w = _make_work(submitted_by=submitter)
    assert w.editable_by(u) is True


# ---- Index view --------------------------------------------------------


@pytest.mark.django_db
def test_index_hides_members_only_listings_from_anonymous(client):
    _make_work(title="Open one", slug="open", listing=Work.Visibility.PUBLIC)
    _make_work(title="Hidden one", slug="hidden", listing=Work.Visibility.MEMBERS)
    body = client.get(reverse("works:index")).content.decode()
    assert "Open one" in body
    assert "Hidden one" not in body


@pytest.mark.django_db
def test_index_has_pdf_filter_excludes_works_with_no_files(client):
    _make_work(title="With file", slug="wf", files=[("", _fake_pdf())])
    _make_work(title="No file", slug="nf", files=None)
    body = client.get(reverse("works:index") + "?has_pdf=1").content.decode()
    assert "With file" in body
    assert "No file" not in body


# ---- Download gating ---------------------------------------------------


@pytest.mark.django_db
def test_download_public_pdf_works_anonymous(client):
    w = _make_work(
        slug="open", pdf_vis=Work.Visibility.PUBLIC,
        files=[("", _fake_pdf())],
    )
    f = w.files.first()
    resp = client.get(reverse("works:download", args=["open", f.pk]))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_download_members_pdf_404s_anonymous(client):
    w = _make_work(
        slug="closed", pdf_vis=Work.Visibility.MEMBERS,
        files=[("", _fake_pdf())],
    )
    f = w.files.first()
    resp = client.get(reverse("works:download", args=["closed", f.pk]))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_download_no_file_404s(client):
    _make_work(slug="nopdf", files=None)
    # Non-existent file id under this work — 404.
    resp = client.get(reverse("works:download", args=["nopdf", 9999]))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_download_cross_work_file_id_404s(client):
    w1 = _make_work(slug="w1", files=[("", _fake_pdf())])
    w2 = _make_work(slug="w2", files=[("", _fake_pdf())])
    f_from_w2 = w2.files.first()
    # Try to download w2's file via w1's slug — should 404.
    resp = client.get(reverse("works:download", args=["w1", f_from_w2.pk]))
    assert resp.status_code == 404
    # And via w1's own file — should 200 (when public).
    w1.pdf_visibility = Work.Visibility.PUBLIC
    w1.save()
    f_w1 = w1.files.first()
    resp = client.get(reverse("works:download", args=["w1", f_w1.pk]))
    assert resp.status_code == 200


# ---- Detail page rendering ---------------------------------------------


@pytest.mark.django_db
def test_detail_single_file_renders_single_button(client):
    _make_work(
        slug="single",
        pdf_vis=Work.Visibility.PUBLIC,
        files=[("", _fake_pdf())],
    )
    body = client.get(reverse("works:detail", args=["single"])).content.decode()
    # Single-file mode shows "Download PDF" (no label, no list heading).
    assert "Download PDF" in body
    assert "<ul" not in body or "PDFs</h2>" not in body


@pytest.mark.django_db
def test_detail_single_file_with_label_uses_it(client):
    _make_work(
        slug="lbl",
        pdf_vis=Work.Visibility.PUBLIC,
        files=[("Author's cut", _fake_pdf())],
    )
    body = client.get(reverse("works:detail", args=["lbl"])).content.decode()
    assert "Download Author&#x27;s cut" in body or "Download Author's cut" in body


@pytest.mark.django_db
def test_detail_multiple_files_renders_list(client):
    _make_work(
        slug="multi",
        pdf_vis=Work.Visibility.PUBLIC,
        files=[("Draft", _fake_pdf("d.pdf")), ("Final", _fake_pdf("f.pdf"))],
    )
    body = client.get(reverse("works:detail", args=["multi"])).content.decode()
    assert "PDFs</h2>" in body
    assert "Draft" in body
    assert "Final" in body


# ---- Add view + form ---------------------------------------------------


@pytest.mark.django_db
def test_add_requires_login(client):
    resp = client.get(reverse("works:add"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_add_creates_work_with_submitter_as_first_author(client):
    u = _make_user()
    client.force_login(u)
    resp = client.post(reverse("works:add"), {
        "title": "My new paper",
        "kind": Work.Kind.EXTERNAL,
        "lsp_authors": "",
        "external_authors": "",
        "abstract": "Hello.",
        "publication_info": "",
        "url": "",
        "publication_date": "",
        "listing_visibility": Work.Visibility.PUBLIC,
        "pdf_visibility": Work.Visibility.MEMBERS,
        "new_file_label": "",
    })
    assert resp.status_code == 302
    w = Work.objects.get(title="My new paper")
    assert w.submitted_by == u
    assert list(w.authors.all()) == [u]


@pytest.mark.django_db
def test_add_with_single_file_creates_workfile():
    u = _make_user()
    form = WorkForm(
        data={
            "title": "Solo paper",
            "kind": Work.Kind.EXTERNAL,
            "lsp_authors": "",
            "external_authors": "",
            "abstract": "",
            "publication_info": "",
            "url": "",
            "publication_date": "",
            "listing_visibility": Work.Visibility.PUBLIC,
            "pdf_visibility": Work.Visibility.PUBLIC,
            "new_file_label": "",
        },
        files={"new_file": _fake_pdf()},
        current_user=u,
    )
    assert form.is_valid(), form.errors
    w = form.save()
    assert w.files.count() == 1
    assert w.files.first().label == ""


# ---- Multi-file edit + label rule --------------------------------------


@pytest.mark.django_db
def test_edit_adding_second_file_without_labels_invalid():
    """Existing file has no label + new file has no label → invalid because total >= 2."""
    u = _make_user()
    w = _make_work(slug="w", submitted_by=u, files=[("", _fake_pdf("a.pdf"))])
    existing = w.files.first()
    form = WorkForm(
        data={
            "title": w.title, "kind": w.kind,
            "lsp_authors": "", "external_authors": "",
            "abstract": "", "publication_info": "", "url": "", "publication_date": "",
            "listing_visibility": Work.Visibility.PUBLIC,
            "pdf_visibility": Work.Visibility.MEMBERS,
            f"file_{existing.pk}_label": "",
            "new_file_label": "",
        },
        files={"new_file": _fake_pdf("b.pdf")},
        instance=w,
        current_user=u,
    )
    assert not form.is_valid()
    # Both fields should error since both files lack a label.
    assert f"file_{existing.pk}_label" in form.errors
    assert "new_file_label" in form.errors


@pytest.mark.django_db
def test_edit_adding_second_file_with_labels_valid():
    u = _make_user()
    w = _make_work(slug="w", submitted_by=u, files=[("", _fake_pdf("a.pdf"))])
    existing = w.files.first()
    form = WorkForm(
        data={
            "title": w.title, "kind": w.kind,
            "lsp_authors": "", "external_authors": "",
            "abstract": "", "publication_info": "", "url": "", "publication_date": "",
            "listing_visibility": Work.Visibility.PUBLIC,
            "pdf_visibility": Work.Visibility.MEMBERS,
            f"file_{existing.pk}_label": "Draft",
            "new_file_label": "Final",
        },
        files={"new_file": _fake_pdf("b.pdf")},
        instance=w,
        current_user=u,
    )
    assert form.is_valid(), form.errors
    w = form.save()
    files = list(w.files.all())
    assert len(files) == 2
    assert {f.label for f in files} == {"Draft", "Final"}


@pytest.mark.django_db
def test_edit_relabel_existing_file():
    u = _make_user()
    w = _make_work(slug="w", submitted_by=u, files=[("Old", _fake_pdf("a.pdf"))])
    existing = w.files.first()
    form = WorkForm(
        data={
            "title": w.title, "kind": w.kind,
            "lsp_authors": "", "external_authors": "",
            "abstract": "", "publication_info": "", "url": "", "publication_date": "",
            "listing_visibility": Work.Visibility.PUBLIC,
            "pdf_visibility": Work.Visibility.MEMBERS,
            f"file_{existing.pk}_label": "New label",
            "new_file_label": "",
        },
        instance=w,
        current_user=u,
    )
    assert form.is_valid(), form.errors
    form.save()
    existing.refresh_from_db()
    assert existing.label == "New label"


@pytest.mark.django_db
def test_edit_remove_existing_file():
    u = _make_user()
    w = _make_work(
        slug="w",
        submitted_by=u,
        files=[("A", _fake_pdf("a.pdf")), ("B", _fake_pdf("b.pdf"))],
    )
    file_a, file_b = list(w.files.all())
    form = WorkForm(
        data={
            "title": w.title, "kind": w.kind,
            "lsp_authors": "", "external_authors": "",
            "abstract": "", "publication_info": "", "url": "", "publication_date": "",
            "listing_visibility": Work.Visibility.PUBLIC,
            "pdf_visibility": Work.Visibility.MEMBERS,
            f"file_{file_a.pk}_label": "A",
            f"file_{file_a.pk}_remove": "on",
            f"file_{file_b.pk}_label": "B",
            "new_file_label": "",
        },
        instance=w,
        current_user=u,
    )
    assert form.is_valid(), form.errors
    form.save()
    remaining = list(w.files.all())
    assert len(remaining) == 1
    assert remaining[0].pk == file_b.pk


@pytest.mark.django_db
def test_edit_remove_dropping_to_single_file_drops_label_requirement():
    """Removing one file from a 2-file work brings it back to single-file
    mode — the remaining file's label is no longer required."""
    u = _make_user()
    w = _make_work(
        slug="w",
        submitted_by=u,
        files=[("Draft", _fake_pdf("a.pdf")), ("Final", _fake_pdf("b.pdf"))],
    )
    file_a, file_b = list(w.files.all())
    form = WorkForm(
        data={
            "title": w.title, "kind": w.kind,
            "lsp_authors": "", "external_authors": "",
            "abstract": "", "publication_info": "", "url": "", "publication_date": "",
            "listing_visibility": Work.Visibility.PUBLIC,
            "pdf_visibility": Work.Visibility.MEMBERS,
            # Clear file_a's label and remove file_b — file_a becomes the only file.
            f"file_{file_a.pk}_label": "",
            f"file_{file_b.pk}_label": "Final",
            f"file_{file_b.pk}_remove": "on",
            "new_file_label": "",
        },
        instance=w,
        current_user=u,
    )
    assert form.is_valid(), form.errors


# ---- Form: author resolution -------------------------------------------


@pytest.mark.django_db
def test_form_resolves_lsp_author_by_name():
    u = _make_user(email="me@x.test", first="Mara", last="Smith")
    co = _make_user(email="co@x.test", first="Paul", last="Adler")
    form = WorkForm(
        data={
            "title": "Joint paper",
            "kind": Work.Kind.EXTERNAL,
            "lsp_authors": "Paul Adler",
            "external_authors": "",
            "abstract": "",
            "publication_info": "",
            "url": "",
            "publication_date": "",
            "listing_visibility": Work.Visibility.PUBLIC,
            "pdf_visibility": Work.Visibility.MEMBERS,
            "new_file_label": "",
        },
        current_user=u,
    )
    assert form.is_valid(), form.errors
    w = form.save()
    ordered = list(
        WorkAuthor.objects.filter(work=w)
        .order_by("display_order")
        .values_list("user", flat=True)
    )
    assert ordered == [u.pk, co.pk]


@pytest.mark.django_db
def test_form_rejects_unknown_author():
    u = _make_user()
    form = WorkForm(
        data={
            "title": "X",
            "kind": Work.Kind.EXTERNAL,
            "lsp_authors": "Nobody In System",
            "external_authors": "",
            "abstract": "",
            "publication_info": "",
            "url": "",
            "publication_date": "",
            "listing_visibility": Work.Visibility.PUBLIC,
            "pdf_visibility": Work.Visibility.MEMBERS,
            "new_file_label": "",
        },
        current_user=u,
    )
    assert not form.is_valid()
    assert "lsp_authors" in form.errors


@pytest.mark.django_db
def test_form_pdf_visibility_constraint_surfaces_on_field():
    u = _make_user()
    form = WorkForm(
        data={
            "title": "X",
            "kind": Work.Kind.EXTERNAL,
            "lsp_authors": "",
            "external_authors": "",
            "abstract": "",
            "publication_info": "",
            "url": "",
            "publication_date": "",
            "listing_visibility": Work.Visibility.MEMBERS,
            "pdf_visibility": Work.Visibility.PUBLIC,
            "new_file_label": "",
        },
        current_user=u,
    )
    assert not form.is_valid()
    assert "pdf_visibility" in form.errors


# ---- Edit permission via view -------------------------------------------


@pytest.mark.django_db
def test_edit_forbidden_for_unrelated_member(client):
    owner = _make_user(email="owner@x.test")
    other = _make_user(email="other@x.test")
    _make_work(slug="w", submitted_by=owner)
    client.force_login(other)
    resp = client.get(reverse("works:edit", args=["w"]))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_edit_allowed_for_submitter(client):
    owner = _make_user(email="owner@x.test")
    _make_work(slug="w", submitted_by=owner)
    client.force_login(owner)
    resp = client.get(reverse("works:edit", args=["w"]))
    assert resp.status_code == 200


# ---- My works ----------------------------------------------------------


@pytest.mark.django_db
def test_my_works_dedupes_when_author_and_submitter():
    u = _make_user()
    w = _make_work(title="W3", slug="w3", submitted_by=u)
    WorkAuthor.objects.create(work=w, user=u, display_order=0)
    from django.db.models import Q
    qs = Work.objects.filter(
        Q(authorships__user=u) | Q(submitted_by=u)
    ).distinct()
    assert qs.filter(slug="w3").count() == 1


# ---- Tone card ---------------------------------------------------------


def test_tone_for_deterministic():
    a = tone_for("My title")
    b = tone_for("My title")
    assert a == b
    assert a in PALETTE


def test_tone_for_distributes_across_palette():
    titles = [f"Title {i}" for i in range(50)]
    colors = {tone_for(t) for t in titles}
    assert len(colors) >= len(PALETTE) // 2


# ---- Directory profile ------------------------------------------------


@pytest.mark.django_db
def test_directory_detail_shows_member_works(client):
    u = _make_user(role=Profile.Role.ANALYST, first="Anne", last="Patsalides")
    w = _make_work(title="Patsalides paper", slug="pp")
    WorkAuthor.objects.create(work=w, user=u, display_order=0)
    body = client.get(reverse("directory_detail", args=[u.profile.directory_slug])).content.decode()
    assert "Patsalides paper" in body
    assert "Selected works" in body


@pytest.mark.django_db
def test_directory_detail_omits_members_only_works_for_anon(client):
    u = _make_user(role=Profile.Role.ANALYST, first="Anne", last="Patsalides")
    w = _make_work(
        title="Secret paper", slug="sp",
        listing=Work.Visibility.MEMBERS,
    )
    WorkAuthor.objects.create(work=w, user=u, display_order=0)
    body = client.get(reverse("directory_detail", args=[u.profile.directory_slug])).content.decode()
    assert "Secret paper" not in body


# ---- PDF rendering (fpdf2, vendored Unicode fonts) ---------------------

def test_render_document_pdf_basics_and_unicode():
    """PDF renders with provenance + members, Unicode text, and lists without
    crashing the (latin-1) core fonts — the vendored DejaVu fonts handle it."""
    import datetime

    from works.pdf import render_document_pdf

    pdf = render_document_pdf(
        title="On the Symptom — café & ψυχή",
        body_html=("<p>café, naïve, Œdipe, Лакан, ψυχή</p>"
                   "<ul><li><p>first</p></li><li><p>second</p></li></ul>"
                   "<ol><li><p>one</p></li><li><p>two</p></li></ol>"),
        group_kind="Cartel", group_name="The Letter",
        members=["Jane Analyst", "Carlos Jiménez"],
        published_date=datetime.date(2026, 6, 2), revision=2,
    )
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 1000


def test_unwrap_list_paragraphs():
    from works.pdf import _unwrap_list_paragraphs

    assert (_unwrap_list_paragraphs("<ul><li><p>a</p></li><li><p>b</p></li></ul>")
            == "<ul><li>a</li><li>b</li></ul>")


# ---- Delete a work -----------------------------------------------------

@pytest.mark.django_db
def test_delete_work_by_submitter(client):
    u = User.objects.create_user(email="a@x.test", password="x")
    w = Work.objects.create(title="Paper", slug="paper", kind=Work.Kind.EXTERNAL,
                            submitted_by=u)
    client.force_login(u)
    resp = client.post(reverse("works:delete", args=[w.slug]))
    assert resp.status_code == 302
    assert resp.url == reverse("works:index")
    assert not Work.objects.filter(pk=w.pk).exists()


@pytest.mark.django_db
def test_delete_work_forbidden_for_non_editor(client):
    owner = User.objects.create_user(email="o@x.test", password="x")
    other = User.objects.create_user(email="x@x.test", password="x")
    w = Work.objects.create(title="Paper", slug="paper", kind=Work.Kind.EXTERNAL,
                            submitted_by=owner)
    client.force_login(other)
    resp = client.post(reverse("works:delete", args=[w.slug]))
    assert resp.status_code == 403
    assert Work.objects.filter(pk=w.pk).exists()


@pytest.mark.django_db
def test_delete_work_requires_post(client):
    u = User.objects.create_user(email="a@x.test", password="x")
    w = Work.objects.create(title="Paper", slug="paper", kind=Work.Kind.EXTERNAL,
                            submitted_by=u)
    client.force_login(u)
    resp = client.get(reverse("works:delete", args=[w.slug]))
    assert resp.status_code == 405                      # require_POST
    assert Work.objects.filter(pk=w.pk).exists()
