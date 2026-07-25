"""The My LSP hub — tab availability, the avatar-menu context processor, the
embedded Profile tab, and the legacy redirects."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import reverse

from accounts.models import Profile, User
from formation.tabs import available_tabs

pytestmark = pytest.mark.django_db


def _user(email, role=Profile.Role.MEMBER):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


# ---- available_tabs --------------------------------------------------------

def test_available_tabs_candidate_full_order():
    u = _user("cand@x.test", role=Profile.Role.CANDIDATE)
    keys = [k for k, _ in available_tabs(u)]
    assert keys == [
        "formation", "groups", "events", "works",
        "account", "proposals", "profile",
    ]


def test_available_tabs_external_has_no_member_tabs():
    u = _user("ext@x.test", role=Profile.Role.EXTERNAL)
    keys = [k for k, _ in available_tabs(u)]
    assert keys == ["formation", "groups", "events", "works", "profile"]


def test_available_tabs_suggestions_requires_flag(settings):
    u = _user("an@x.test", role=Profile.Role.ANALYST)
    settings.SUGGESTIONS_ENABLED = True
    assert "suggestions" in [k for k, _ in available_tabs(u)]
    settings.SUGGESTIONS_ENABLED = False
    assert "suggestions" not in [k for k, _ in available_tabs(u)]


def test_available_tabs_anonymous_empty():
    assert available_tabs(AnonymousUser()) == []


# ---- context processor + avatar menu ---------------------------------------

def test_context_processor_exposes_tabs(client):
    client.force_login(_user("cp@x.test", role=Profile.Role.ANALYST))
    resp = client.get(reverse("core:landing"))
    assert "my_lsp_tabs" in resp.context
    keys = [k for k, _ in resp.context["my_lsp_tabs"]]
    assert keys[0] == "formation" and keys[-1] == "profile"


def test_context_processor_empty_for_anonymous(client):
    resp = client.get(reverse("core:landing"))
    assert resp.context["my_lsp_tabs"] == []


def test_avatar_menu_shows_my_lsp(client):
    client.force_login(_user("nav@x.test", role=Profile.Role.ANALYST))
    body = client.get(reverse("core:landing")).content
    assert b">My LSP<" in body
    assert b"?tab=groups" in body and b"?tab=profile" in body


# ---- tab rendering + gating ------------------------------------------------

def test_works_tab_renders(client):
    client.force_login(_user("w@x.test", role=Profile.Role.ANALYST))
    body = client.get(reverse("formation:formation") + "?tab=works").content
    assert b"Add a work" in body


def test_unavailable_tab_falls_back_to_formation(client):
    """A non-member hand-typing ?tab=proposals gets the Formation tab, not a leak."""
    client.force_login(_user("ext2@x.test", role=Profile.Role.EXTERNAL))
    resp = client.get(reverse("formation:formation") + "?tab=proposals")
    assert resp.status_code == 200
    assert b"My Advisor" in resp.content


def test_profile_tab_embeds_editor(client):
    client.force_login(_user("p@x.test", role=Profile.Role.ANALYST))
    body = client.get(reverse("formation:formation") + "?tab=profile").content
    assert b'id="profile-form"' in body          # the editor form
    assert b'id="cropper-modal"' in body         # the headshot cropper
    assert b'name="next"' in body                # posts back to the tab
    assert b"tab=profile" in body


# ---- profile-save redirect logic -------------------------------------------

def test_profile_saved_redirect_honors_next():
    from accounts.views import _profile_saved_redirect

    next_url = reverse("formation:formation") + "?tab=profile"
    req = RequestFactory().post("/accounts/profile/", {"next": next_url})
    url = _profile_saved_redirect(req)
    assert url.startswith(next_url) and "saved=1" in url


def test_profile_saved_redirect_fallback():
    from accounts.views import _profile_saved_redirect

    req = RequestFactory().post("/accounts/profile/")
    assert _profile_saved_redirect(req) == reverse("profile_edit") + "?saved=1#saved"


# ---- formation-doc link on the Formation tab -------------------------------

def _formation_doc(slug, title):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from documents.models import Document

    return Document.objects.create(
        title=title,
        slug=slug,
        category=Document.Category.FORMATION,
        summary="Guidelines.",
        listing_visibility=Document.Visibility.MEMBERS,
        content_visibility=Document.Visibility.MEMBERS,
        file=SimpleUploadedFile("g.pdf", b"%PDF-1.4\n", content_type="application/pdf"),
    )


def _set_formation_docs(*, analyst=None, scholar=None):
    from formation.models import FormationSettings

    s = FormationSettings.load()
    s.analyst_formation_doc = analyst
    s.scholar_formation_doc = scholar
    s.save()


def test_in_training_analyst_sees_analyst_doc(client):
    analyst_doc = _formation_doc("analyst-g", "Analyst Formation Guidelines")
    scholar_doc = _formation_doc("scholar-g", "Scholar Formation Guidelines")
    _set_formation_docs(analyst=analyst_doc, scholar=scholar_doc)
    client.force_login(_user("pc@x.test", role=Profile.Role.PRE_CANDIDATE))
    body = client.get(reverse("formation:formation")).content
    assert analyst_doc.get_absolute_url().encode() in body
    assert scholar_doc.get_absolute_url().encode() not in body


def test_in_training_scholar_sees_scholar_doc(client):
    analyst_doc = _formation_doc("analyst-g", "Analyst Formation Guidelines")
    scholar_doc = _formation_doc("scholar-g", "Scholar Formation Guidelines")
    _set_formation_docs(analyst=analyst_doc, scholar=scholar_doc)
    client.force_login(_user("pcs@x.test", role=Profile.Role.PRE_CANDIDATE_SCHOLAR))
    body = client.get(reverse("formation:formation")).content
    assert scholar_doc.get_absolute_url().encode() in body
    assert analyst_doc.get_absolute_url().encode() not in body


def test_graduated_analyst_sees_no_doc(client):
    analyst_doc = _formation_doc("analyst-g", "Analyst Formation Guidelines")
    _set_formation_docs(analyst=analyst_doc)
    client.force_login(_user("an2@x.test", role=Profile.Role.ANALYST))
    resp = client.get(reverse("formation:formation"))
    assert resp.context["formation_doc"] is None
    assert analyst_doc.get_absolute_url().encode() not in resp.content


def test_plain_member_sees_no_doc(client):
    analyst_doc = _formation_doc("analyst-g", "Analyst Formation Guidelines")
    _set_formation_docs(analyst=analyst_doc)
    client.force_login(_user("m2@x.test", role=Profile.Role.MEMBER))
    assert client.get(reverse("formation:formation")).context["formation_doc"] is None


def test_link_absent_when_doc_unset(client):
    _set_formation_docs(analyst=None, scholar=None)
    client.force_login(_user("pc2@x.test", role=Profile.Role.PRE_CANDIDATE))
    assert client.get(reverse("formation:formation")).context["formation_doc"] is None


# ---- Statement ordering -----------------------------------------------------

def test_statement_ordered_by_paid_at_not_created_at():
    """The Account tab statement (``payments.ledger.member_account``) orders
    its lines chronologically (oldest first) off each line's displayed
    date — paid_at, falling back to created_at — not created_at alone. A
    backfilled offline payment is entered (created) after a newer Stripe
    payment but paid earlier, so created_at and the displayed date diverge
    (ported from the retired My Payments table's ordering test, task #439)."""
    from datetime import datetime
    from datetime import timezone as tz

    from django.utils import timezone

    from payments import ledger
    from payments.models import Payment

    u = _user("pay@x.test", role=Profile.Role.ANALYST)

    def _mk(amount, created_at, paid_at):
        p = Payment.objects.create(
            user=u,
            payment_type=Payment.Type.DUES,
            amount=amount,
            status=Payment.Status.SUCCEEDED,
            method=Payment.Method.OFFLINE,
            paid_at=paid_at,
        )
        # created_at is auto_now_add — override it after the fact.
        Payment.objects.filter(pk=p.pk).update(created_at=created_at)
        return p

    old_paid = datetime(2026, 1, 15, tzinfo=tz.utc)
    new_paid = datetime(2026, 7, 1, tzinfo=tz.utc)
    # The old charge was *entered* today (created_at newest) but paid in January.
    backfill = _mk("50.00", created_at=timezone.now(), paid_at=old_paid)
    # The recent charge was created earlier but paid in July.
    recent = _mk("60.00", created_at=datetime(2026, 6, 20, tzinfo=tz.utc), paid_at=new_paid)

    acct = ledger.member_account(u)
    ids = [ln["obj"].id for ln in acct["lines"] if ln["kind"] == "payment"]
    # Chronological order (oldest first, the statement's convention) driven
    # by paid_at, not created_at.
    assert ids == [backfill.id, recent.id]


# ---- legacy redirects ------------------------------------------------------

def test_legacy_list_pages_redirect(client):
    client.force_login(_user("r@x.test", role=Profile.Role.ANALYST))
    for name, tab in (
        ("works:mine", "works"),
        ("my_proposals", "proposals"),
        ("workgroups:mine", "groups"),
        ("suggestions:mine", "suggestions"),
    ):
        resp = client.get(reverse(name))
        assert resp.status_code == 302 and f"tab={tab}" in resp.url
