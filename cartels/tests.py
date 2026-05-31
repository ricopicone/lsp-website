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
    u = _member(email)
    u.profile.is_cartel_coordinator = True
    u.profile.save(update_fields=["is_cartel_coordinator"])
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
