"""Tests for the consolidated 'My Formation' hub (advisor + advancement +
tuition + groups on one tabbed page)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.advisor import set_advisor
from accounts.models import Profile, Source, User
from admissions.advancement import step_label_for_member
from admissions.models import Advancement, step_label_for

pytestmark = pytest.mark.django_db


def _user(email, role=Profile.Role.PRE_CANDIDATE):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


# ---- track-aware step labels ----------------------------------------------

def test_step_label_passage_vs_traversee():
    # Palimpsest is the same word on both tracks.
    palimpsest = Advancement.Kind.PALIMPSEST
    assert step_label_for(palimpsest, Profile.Role.PRE_CANDIDATE) == "Palimpsest"
    assert step_label_for(palimpsest, Profile.Role.PRE_CANDIDATE_SCHOLAR) == "Palimpsest"
    # The passage step: Passage on the Analyst track, Traversée on the Scholar track.
    assert step_label_for(Advancement.Kind.PASSAGE, Profile.Role.CANDIDATE) == "Passage"
    assert step_label_for(Advancement.Kind.PASSAGE, Profile.Role.CANDIDATE_SCHOLAR) == "Traversée"


def test_step_label_for_member_and_model_property():
    analyst_track = _user("cand@x.test", role=Profile.Role.CANDIDATE)
    scholar_track = _user("cand-s@x.test", role=Profile.Role.CANDIDATE_SCHOLAR)
    assert step_label_for_member(analyst_track) == "Passage"
    assert step_label_for_member(scholar_track) == "Traversée"

    adv = Advancement.objects.create(
        member=scholar_track, kind=Advancement.Kind.PASSAGE,
        from_role=Profile.Role.CANDIDATE_SCHOLAR, statement="",
    )
    assert adv.step_label == "Traversée"


# ---- the demande is just a request (no file upload) -----------------------

def test_demande_opens_with_blank_statement(client, django_capture_on_commit_callbacks):
    advisor = _user("an@x.test", role=Profile.Role.ANALYST)
    member = _user("pc@x.test")
    set_advisor(member, advisor, by=member)
    client.force_login(member)
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(reverse("admissions:advancement"), {"statement": ""})
    assert resp.status_code == 302
    assert Advancement.objects.filter(member=member, status="requested").exists()


# ---- the tabbed page renders ----------------------------------------------

def test_formation_page_shows_tabs_for_candidate(client):
    member = _user("c@x.test", role=Profile.Role.CANDIDATE)
    client.force_login(member)
    body = client.get(reverse("admissions:formation")).content
    assert b"My Formation" in body
    assert b"Formation" in body and b"Tuition" in body and b"Groups" in body


# ---- groups tab ------------------------------------------------------------

def test_groups_tab_lists_current_and_past(client):
    from workgroups.models import Workgroup, WorkgroupMembership

    member = _user("g@x.test", role=Profile.Role.MEMBER)
    current = Workgroup.objects.create(kind=Workgroup.Kind.CARTEL, name="Desire Cartel")
    past = Workgroup.objects.create(kind=Workgroup.Kind.WORKING_GROUP, name="Old WG")
    WorkgroupMembership.objects.create(
        workgroup=current, user=member,
        role=WorkgroupMembership.Role.MEMBER, start_date=date(2024, 1, 1),
    )
    WorkgroupMembership.objects.create(
        workgroup=past, user=member, role=WorkgroupMembership.Role.MEMBER,
        start_date=date(2020, 1, 1), end_date=date(2021, 1, 1),
    )
    client.force_login(member)
    body = client.get(reverse("admissions:formation") + "?tab=groups").content
    assert b"Desire Cartel" in body
    assert b"Old WG" in body
    assert b"Current groups" in body and b"Past groups" in body


# ---- self-reconcile of own provisional payments ---------------------------

def test_member_reconciles_own_assumed_payment(client):
    from payments.models import Payment

    member = _user("r@x.test", role=Profile.Role.CANDIDATE)
    other = _user("other@x.test", role=Profile.Role.CANDIDATE)
    mine = Payment.objects.create(
        payment_type=Payment.Type.TUITION, user=member, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, source=Source.ASSUMED,
    )
    theirs = Payment.objects.create(
        payment_type=Payment.Type.TUITION, user=other, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, source=Source.ASSUMED,
    )
    client.force_login(member)
    resp = client.post(reverse("my_payment_reconcile"), {
        "payment_ids": [str(mine.id), str(theirs.id)],  # theirs must be ignored
        "payment_type": "donation",
    })
    assert resp.status_code == 302
    mine.refresh_from_db()
    theirs.refresh_from_db()
    assert mine.payment_type == "donation"
    assert mine.source == Source.SELF_REPORTED
    # A member can't touch someone else's payment even by passing its id.
    assert theirs.payment_type == "tuition"
    assert theirs.source == Source.ASSUMED
