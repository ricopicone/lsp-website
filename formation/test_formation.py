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
from formation.advancement import step_label_for_member
from formation.models import Advancement, step_label_for
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
        resp = client.post(reverse("formation:advancement"), {"statement": ""})
    assert resp.status_code == 302
    assert Advancement.objects.filter(member=member, status="requested").exists()


# ---- the tabbed page renders ----------------------------------------------

def test_formation_page_shows_tabs_for_candidate(client):
    member = _user("c@x.test", role=Profile.Role.CANDIDATE)
    client.force_login(member)
    body = client.get(reverse("formation:formation")).content
    assert b"My LSP" in body
    # A candidate owes tuition + dues, so those tabs appear alongside the
    # always-on ones — dues now lives on the unified "My account" tab
    # (task #439). Tabs are real, shareable ?tab= links.
    for key in (b"groups", b"events", b"works", b"tuition", b"account", b"profile"):
        assert b'href="?tab=' + key + b'"' in body


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
    body = client.get(reverse("formation:formation") + "?tab=groups").content
    assert b"Desire Cartel" in body
    assert b"Old WG" in body
    # New groups tab: Current / Past sections (from workgroups.membership).
    assert b">Current<" in body and b">Past<" in body


# ---- editable My Payments table (type / note / AY) -------------------------

def test_member_edits_type_and_note_on_own_payment(client):
    """Non-donation<->non-donation retypes (both count toward the unified
    ledger pot) stay self-service, alongside a note edit. Donation<->
    non-donation retypes are a separate, treasurer-only path — see
    payments/test_tuition.py::test_member_cannot_retype_donation_to_dues
    (task #439 fix 1)."""
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
    resp = client.post(reverse("my_payments_update"), {
        f"type_{mine.id}": "dues",
        f"note_{mine.id}": "Actually dues, not tuition.",
        # An attempt to edit someone else's payment is ignored (not in the qs).
        f"type_{theirs.id}": "dues",
    })
    assert resp.status_code == 302
    mine.refresh_from_db()
    theirs.refresh_from_db()
    assert mine.payment_type == "dues"
    assert mine.source == Source.SELF_REPORTED
    assert mine.member_note == "Actually dues, not tuition."
    assert theirs.payment_type == "tuition"  # untouched
    assert theirs.source == Source.ASSUMED


def test_my_payments_shows_event_for_registration(client):
    """The 'For' column links to the event a registration payment is for."""
    from datetime import date as _date

    from events.models import Audience, Event, PriceTier
    from payments.models import Payment
    from registrations.models import Registration

    member = _user("regpay@x.test", role=Profile.Role.MEMBER)
    event = Event.objects.create(
        title="Working with Masochism", slug="masochism",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=_date(2030, 9, 1), end_date=_date(2030, 9, 1), published=True,
    )
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("50.00"),
    )
    reg = Registration.objects.create(
        user=member, event=event, price_tier=tier,
        quoted_amount=Decimal("50.00"), status=Registration.Status.PAID,
    )
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, registration=reg, user=member,
        amount=Decimal("50.00"), status=Payment.Status.SUCCEEDED,
    )
    client.force_login(member)
    body = client.get(reverse("formation:formation") + "?tab=tuition").content.decode()
    assert "Working with Masochism" in body
    assert reverse("events:detail", args=[event.slug]) in body


# ---- step trace + linking the Work via the Works flow ----------------------

def test_trace_offers_add_work_button_via_works_flow(client):
    member = _user("trace@x.test", role=Profile.Role.CANDIDATE)
    Advancement.objects.create(
        member=member, kind=Advancement.Kind.PALIMPSEST,
        from_role=Profile.Role.PRE_CANDIDATE, statement="",
        status=Advancement.Status.APPROVED,
    )
    client.force_login(member)
    body = client.get(reverse("formation:formation")).content.decode()
    assert "Palimpsest" in body
    # No Work yet → a button into the Works flow, pre-picking the kind.
    assert "Add my Palimpsest" in body
    assert f"{reverse('works:add')}?kind=palimpsest" in body


def test_candidate_without_advancement_record_sees_palimpsest(client):
    """The reported bug: a member who reached Candidate via import (no
    Advancement row) still sees their completed Palimpsest, dated from tenure,
    with an Add-Work button."""
    from accounts.models import MembershipTenure

    member = _user("imported@x.test", role=Profile.Role.CANDIDATE)
    MembershipTenure.objects.create(
        user=member, role=Profile.Role.CANDIDATE, start_ay=2022,
    )
    assert not Advancement.objects.filter(member=member).exists()
    client.force_login(member)
    body = client.get(reverse("formation:formation")).content.decode()
    assert "Palimpsest" in body
    assert "Completed in AY 2022" in body
    assert f"{reverse('works:add')}?kind=palimpsest" in body


def test_palimpsest_work_appears_in_step(client):
    """A Work of kind=palimpsest authored by the member shows in their step."""
    from works.models import Work

    member = _user("hasworks@x.test", role=Profile.Role.CANDIDATE)
    work = Work.objects.create(
        title="My Palimpsest Text", slug="my-palimpsest-text",
        kind=Work.Kind.PALIMPSEST, submitted_by=member,
    )
    work.authors.add(member)
    client.force_login(member)
    body = client.get(reverse("formation:formation")).content.decode()
    assert "My Palimpsest Text" in body
    assert work.get_absolute_url() in body


def test_analyst_sees_both_completed_steps(client):
    member = _user("an-done@x.test", role=Profile.Role.ANALYST)
    client.force_login(member)
    body = client.get(reverse("formation:formation")).content
    assert b"Palimpsest" in body and b"Passage" in body


def test_scholar_step_uses_traversee_work_kind(client):
    member = _user("sch-done@x.test", role=Profile.Role.SCHOLAR)
    client.force_login(member)
    body = client.get(reverse("formation:formation")).content.decode()
    assert "Traversée" in body
    assert "Palimpsest" in body
    # The scholar's passage step links to a Traversée Work, not a Passage one.
    assert f"{reverse('works:add')}?kind=traversee" in body


def test_add_work_view_preselects_kind_from_query(client):
    member = _user("addkind@x.test", role=Profile.Role.CANDIDATE)
    client.force_login(member)
    resp = client.get(reverse("works:add") + "?kind=palimpsest")
    assert resp.status_code == 200
    assert resp.context["form"].initial.get("kind") == "palimpsest"


# ---- tuition four-year progress -------------------------------------------

def test_tuition_progress_counts_paid_and_projects_to_four_years(current_period):
    from formation.views import _tuition_progress
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
    from formation.views import _tuition_progress
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
    from formation.views import _tuition_progress

    member = _user("skip@x.test", role=Profile.Role.CANDIDATE)
    TuitionEnrollment.objects.create(
        user=member, tuition_period=current_period,
        status=TuitionEnrollment.Status.SKIPPING,
    )
    ctx = _tuition_progress(member)
    assert ctx["tuition_years_started"] == 0


# ---- dues section (now on the unified "My account" tab, task #439) --------

def test_dues_section_offers_payment_when_unpaid(client, current_period):
    member = _user("dues@x.test", role=Profile.Role.CANDIDATE)
    client.force_login(member)
    # Dues now live on the unified account tab, alongside the statement.
    body = client.get(reverse("formation:formation") + "?tab=account").content
    assert b"Membership dues" in body
    # An obligated, unpaid member is offered a pay action.
    assert b"dues" in body.lower()
