"""Tests for the cartel CART-4 formation/joining workflow."""

from __future__ import annotations

import pytest

from accounts.models import Profile, User
from cartels.models import Cartel, CartelJoinRequest
from cartels.permissions import is_cartel_coordinator
from workgroups.models import Visibility, WorkgroupMembership

pytestmark = pytest.mark.django_db


def _member(email):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    return u


def _coordinator(email="coord@x.test"):
    from core.models import StaffRole

    u = _member(email)
    StaffRole.objects.get(key=StaffRole.CARTEL_COORDINATOR).holders.add(u)
    return u


# ---- propose ----------------------------------------------------------

def test_propose_creates_proposed_cartel_with_generator_as_member():
    gen = _member("gen@x.test")
    invitee = _member("inv@x.test")
    cartel = Cartel.objects.propose(
        generator=gen, name="Speech and Writing",
        guiding_question="What is a letter?", invitees=[invitee],
    )
    assert cartel.status == Cartel.Status.PROPOSED
    assert cartel.workgroup.landing_visibility == Visibility.PRIVATE   # hidden pre-approval
    assert cartel.is_member(gen) is True
    assert cartel.invitations.filter(invited_user=invitee).exists()
    # not visible to the school yet
    assert cartel.workgroup.landing_visible_to(_member("outsider@x.test")) is False


# ---- coordinator review ------------------------------------------------

def test_is_cartel_coordinator_designation():
    assert is_cartel_coordinator(_member("plain@x.test")) is False
    assert is_cartel_coordinator(_coordinator()) is True


def test_approve_publishes_open_and_records_reviewer():
    gen = _member("gen@x.test")
    coord = _coordinator()
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(coord)
    assert cartel.status == Cartel.Status.OPEN
    assert cartel.reviewed_by == coord and cartel.reviewed_at is not None
    assert cartel.workgroup.landing_visibility == Visibility.MEMBERS   # now solicitable
    assert cartel.workgroup.landing_visible_to(_member("anymember@x.test")) is True


def test_decline_records_reason():
    cartel = Cartel.objects.propose(generator=_member("g@x.test"), name="C")
    cartel.decline(_coordinator(), note="Too close to an existing cartel.")
    assert cartel.status == Cartel.Status.DECLINED
    assert "existing cartel" in cartel.review_note


# ---- joining -----------------------------------------------------------

def test_seeded_invitee_joins_directly():
    gen = _member("g@x.test")
    invitee = _member("inv@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C", invitees=[invitee])
    cartel.approve(_coordinator())
    cartel.accept_invitation(invitee)
    assert cartel.is_member(invitee) is True
    assert cartel.invitations.get(invited_user=invitee).accepted_at is not None


def test_uninvited_applicant_is_member_gated():
    gen = _member("g@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    applicant = _member("appl@x.test")

    req = cartel.request_to_join(applicant)
    assert req.status == CartelJoinRequest.Status.PENDING
    assert cartel.is_member(applicant) is False     # not yet — gated

    cartel.accept_request(req, decided_by=gen)       # an existing member accepts
    req.refresh_from_db()
    assert req.status == CartelJoinRequest.Status.ACCEPTED
    assert req.decided_by == gen
    assert cartel.is_member(applicant) is True        # now a member, can gate others


def test_decline_request_keeps_applicant_out():
    cartel = Cartel.objects.propose(generator=_member("g@x.test"), name="C")
    cartel.approve(_coordinator())
    applicant = _member("appl@x.test")
    req = cartel.request_to_join(applicant)
    cartel.decline_request(req, decided_by=cartel.generator)
    req.refresh_from_db()
    assert req.status == CartelJoinRequest.Status.DECLINED
    assert cartel.is_member(applicant) is False


def test_plus_one_is_a_membership_role():
    gen = _member("g@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    p1 = _member("plusone@x.test")
    cartel.add_member(p1, plus_one=True)
    assert cartel.workgroup.memberships.filter(
        user=p1, role=WorkgroupMembership.Role.PLUS_ONE, end_date__isnull=True
    ).exists()


# ---- views (end-to-end through HTTP) ----------------------------------

def test_propose_view_creates_cartel_and_redirects(client):
    gen = _member("gen@x.test")
    client.force_login(gen)
    resp = client.post("/cartels/propose/", {
        "name": "Speech and Writing",
        "guiding_question": "What is a letter?",
        "description": "Reading the Écrits.",
        "invitees": "",
    })
    assert resp.status_code == 302
    cartel = Cartel.objects.get(workgroup__name="Speech and Writing")
    assert cartel.status == Cartel.Status.PROPOSED
    assert cartel.is_member(gen)


def test_propose_view_blocks_non_members(client):
    from accounts.models import User
    # role defaults to external (not an LSP member)
    guest = User.objects.create_user(email="guest@x.test", password="x")
    client.force_login(guest)
    resp = client.post("/cartels/propose/", {"name": "X", "guiding_question": "Q"})
    assert resp.status_code == 404
    assert not Cartel.objects.filter(workgroup__name="X").exists()


def test_review_queue_gated_to_coordinator(client):
    plain = _member("plain@x.test")
    client.force_login(plain)
    assert client.get("/cartels/review/").status_code == 404
    client.force_login(_coordinator())
    assert client.get("/cartels/review/").status_code == 200


def test_coordinator_approves_via_view(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    coord = _coordinator()
    client.force_login(coord)
    resp = client.post(f"/cartels/review/{cartel.pk}/decide/", {"decision": "approve"})
    assert resp.status_code == 302
    cartel.refresh_from_db()
    assert cartel.status == Cartel.Status.OPEN


def test_apply_and_member_accepts_via_views(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    applicant = _member("appl@x.test")

    client.force_login(applicant)
    resp = client.post(f"/cartels/{cartel.workgroup.slug}/apply/")
    assert resp.status_code == 302
    req = CartelJoinRequest.objects.get(cartel=cartel, applicant=applicant)
    assert req.status == CartelJoinRequest.Status.PENDING

    client.force_login(gen)   # an existing member gates
    resp = client.post(
        f"/cartels/{cartel.workgroup.slug}/requests/{req.pk}/decide/", {"decision": "accept"}
    )
    assert resp.status_code == 302
    assert cartel.is_member(applicant)


def test_propose_form_renders(client):
    client.force_login(_member("gen@x.test"))
    resp = client.get("/cartels/propose/")
    assert resp.status_code == 200
    assert b"Propose a cartel" in resp.content


def test_cartel_ui_composed_into_unified_groups_detail(client):
    """The cartel UI now renders on the unified /groups/<slug>/ page — guiding
    question, member-gating, and roster — composed from the cartel partial."""
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C", guiding_question="What is a letter?")
    cartel.approve(_coordinator())
    cartel.request_to_join(_member("appl@x.test"))
    client.force_login(gen)
    resp = client.get(cartel.workgroup.get_absolute_url())   # /groups/<slug>/
    assert resp.status_code == 200
    assert b"What is a letter?" in resp.content   # guiding question
    assert b"Applications" in resp.content         # member-gating UI
    assert b"Members" in resp.content


def test_groups_detail_shows_apply_to_eligible_member(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    client.force_login(_member("outsider@x.test"))
    resp = client.get(cartel.workgroup.get_absolute_url())
    assert resp.status_code == 200
    assert b"Apply to join" in resp.content


def test_legacy_cartel_urls_redirect_to_groups(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    slug = cartel.workgroup.slug
    client.force_login(gen)
    assert client.get("/cartels/").status_code == 302
    assert client.get(f"/cartels/{slug}/").status_code == 302
    assert client.get(f"/cartels/{slug}/", follow=True).status_code == 200


def test_proposed_cartel_hidden_from_other_members_on_kind_list(client):
    gen = _member("gen@x.test")
    Cartel.objects.propose(generator=gen, name="Secret Proposal")
    other = _member("other@x.test")
    client.force_login(other)
    resp = client.get("/groups/cartels/")
    assert b"Secret Proposal" not in resp.content   # private until approved
