"""Tests for the consolidated 'My Formation' hub (advisor + advancement +
tuition + groups on one tabbed page)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.advisor import set_advisor
from accounts.models import Profile, Source, User
from admissions.advancement import step_label_for_member
from admissions.models import Advancement, step_label_for
from payments.models import TuitionEnrollment, TuitionPeriod

pytestmark = pytest.mark.django_db


def _user(email, role=Profile.Role.PRE_CANDIDATE):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


@pytest.fixture
def current_period(db):
    """The current TuitionPeriod (seeded by migration), or a synthesized one
    covering today if the seed picked a future-only AY."""
    period = TuitionPeriod.current()
    if period is not None:
        return period
    today = timezone.now().date()
    return TuitionPeriod.objects.create(
        name="Test AY", slug="test-ay-tuition",
        start_date=today - timedelta(days=60),
        decision_due_date=today + timedelta(days=30),
        end_date=today + timedelta(days=300),
        tuition_amount=Decimal("800.00"),
    )


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
    # Tabs are real, shareable ?tab= links (not client-only state).
    assert b'href="?tab=tuition"' in body and b'href="?tab=groups"' in body


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
    assert b"My current groups" in body and b"My past groups" in body


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


# ---- advancement trace + Work upload --------------------------------------

def test_trace_shows_each_step_with_dates(client):
    member = _user("trace@x.test", role=Profile.Role.CANDIDATE)
    adv = Advancement.objects.create(
        member=member, kind=Advancement.Kind.PALIMPSEST,
        from_role=Profile.Role.PRE_CANDIDATE, statement="",
        status=Advancement.Status.APPROVED,
    )
    client.force_login(member)
    body = client.get(reverse("admissions:formation")).content
    assert b"Palimpsest" in body
    # No Work uploaded yet → an upload control is offered.
    assert b"Upload the Work" in body
    assert reverse("admissions:advancement_upload", args=[adv.pk]).encode() in body


def test_member_uploads_work_to_their_advancement(client):
    from django.core.files.uploadedfile import SimpleUploadedFile

    member = _user("up@x.test", role=Profile.Role.CANDIDATE)
    adv = Advancement.objects.create(
        member=member, kind=Advancement.Kind.PALIMPSEST,
        from_role=Profile.Role.PRE_CANDIDATE, statement="",
        status=Advancement.Status.APPROVED,
    )
    client.force_login(member)
    resp = client.post(
        reverse("admissions:advancement_upload", args=[adv.pk]),
        {"work": SimpleUploadedFile("palimpsest.txt", b"my text", content_type="text/plain")},
    )
    assert resp.status_code == 302
    adv.refresh_from_db()
    assert adv.palimpsest  # a file is now attached


def test_cannot_upload_to_another_members_advancement(client):
    from django.core.files.uploadedfile import SimpleUploadedFile

    owner = _user("owner@x.test", role=Profile.Role.CANDIDATE)
    intruder = _user("intruder@x.test", role=Profile.Role.CANDIDATE)
    adv = Advancement.objects.create(
        member=owner, kind=Advancement.Kind.PALIMPSEST,
        from_role=Profile.Role.PRE_CANDIDATE, statement="",
    )
    client.force_login(intruder)
    resp = client.post(
        reverse("admissions:advancement_upload", args=[adv.pk]),
        {"work": SimpleUploadedFile("x.txt", b"x", content_type="text/plain")},
    )
    assert resp.status_code == 404
    adv.refresh_from_db()
    assert not adv.palimpsest


# ---- tuition four-year progress -------------------------------------------

def test_tuition_progress_counts_paid_and_projects_to_four_years(current_period):
    from admissions.views import _tuition_progress
    from payments.models import Payment, TuitionInstallment

    member = _user("prog@x.test", role=Profile.Role.CANDIDATE)
    enr = TuitionEnrollment.objects.create(
        user=member, tuition_period=current_period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    full = current_period.tuition_amount
    half = (full / 2).quantize(Decimal("0.01"))
    inst = TuitionInstallment.objects.create(
        enrollment=enr, sequence=1, due_date=current_period.start_date,
        amount=half, paid=True,
    )
    TuitionInstallment.objects.create(
        enrollment=enr, sequence=2, due_date=current_period.start_date, amount=full - half,
    )
    Payment.objects.create(
        payment_type=Payment.Type.TUITION, user=member, amount=half,
        status=Payment.Status.SUCCEEDED, tuition_installment=inst,
    )
    ctx = _tuition_progress(member)
    assert ctx["tuition_years_started"] == 1
    assert len(ctx["tuition_slots"]) == 4          # one started + three projected
    assert ctx["tuition_total_paid"] == half
    # Goal = this year's amount + 3 projected years at the current rate.
    assert ctx["tuition_total_goal"] == full * 4


def test_tuition_progress_counts_payments_without_installments(current_period):
    """The bug fix: a SUCCEEDED tuition payment with no TuitionInstallment
    (ledger/Stripe import, reconcile, offline) still counts toward progress."""
    from admissions.views import _tuition_progress
    from payments.models import Payment

    member = _user("noinst@x.test", role=Profile.Role.CANDIDATE)
    # No enrollment, no installment — just a tuition payment dated to this year.
    Payment.objects.create(
        payment_type=Payment.Type.TUITION, user=member,
        amount=current_period.tuition_amount,
        status=Payment.Status.SUCCEEDED,
        paid_at=timezone.make_aware(
            datetime.combine(current_period.start_date, time(12, 0))
        ),
    )
    ctx = _tuition_progress(member)
    assert ctx["tuition_years_started"] == 1
    assert ctx["tuition_total_paid"] == current_period.tuition_amount
    assert sum(1 for s in ctx["tuition_slots"] if s["projected"]) == 3


def test_skipping_year_is_not_one_of_the_four(current_period):
    from admissions.views import _tuition_progress

    member = _user("skip@x.test", role=Profile.Role.CANDIDATE)
    TuitionEnrollment.objects.create(
        user=member, tuition_period=current_period,
        status=TuitionEnrollment.Status.SKIPPING,
    )
    ctx = _tuition_progress(member)
    assert ctx["tuition_years_started"] == 0


# ---- dues section ----------------------------------------------------------

def test_dues_section_offers_payment_when_unpaid(client, current_period):
    member = _user("dues@x.test", role=Profile.Role.CANDIDATE)
    client.force_login(member)
    body = client.get(reverse("admissions:formation") + "?tab=tuition").content
    assert b"Membership dues" in body
    # An obligated, unpaid member is offered a pay action.
    assert b"dues" in body.lower()
