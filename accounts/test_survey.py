"""Tests for the member intake survey (apply + reconciliation + view + nudge)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import MemberIntakeSurvey, MembershipTenure, Profile, Source, User
from accounts.survey import (
    apply_survey,
    milestone_questions,
    parse_grid,
    parse_milestones,
    survey_year_rows,
)
from payments.models import DuesPeriod, Payment, TuitionEnrollment, TuitionPeriod

pytestmark = pytest.mark.django_db


def _member(email="m@x.test", role=Profile.Role.CANDIDATE):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


def _periods(year=2023):
    tp = TuitionPeriod.objects.create(
        name=f"AY {year}", slug=f"ay-{year}-t",
        start_date=date(year, 9, 1), decision_due_date=date(year, 10, 1),
        end_date=date(year + 1, 8, 31), tuition_amount=Decimal("2000.00"),
    )
    dp = DuesPeriod.objects.create(
        name=f"AY {year} dues", slug=f"ay-{year}-d",
        start_date=date(year, 9, 1), end_date=date(year + 1, 8, 31),
        due_date=date(year, 12, 1),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"), dues_amount_analyst=Decimal("150"),
    )
    return tp, dp


def _tuition(user, amount, when, *, source=Source.IMPORTED):
    return Payment.objects.create(
        payment_type=Payment.Type.TUITION, user=user, amount=Decimal(amount),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.STRIPE,
        source=source, paid_at=timezone.make_aware(when),
    )


def _apply(user, grid, *, year_joined=2020, milestones=None):
    return apply_survey(user, year_joined=year_joined, pronouns=None,
                        payment_names="", payment_emails="", grid=grid,
                        milestones=milestones)


# ---- parsing & prefill -----------------------------------------------------

def test_parse_grid():
    post = {"tuition_2023": "full", "tuition_2022": "partial",
            "dues_2023": "on", "other": "x"}
    assert parse_grid(post) == {
        "2023": {"tuition": "full", "dues": True}, "2022": {"tuition": "partial"},
    }


def test_parse_milestones():
    assert parse_milestones({"milestone_palimpsest": "2019",
                             "milestone_passage": "", "x": "y"}) == {"palimpsest": 2019}


def test_year_rows_state_from_records():
    tp, dp = _periods(2023)
    u = _member()
    Payment.objects.create(
        payment_type=Payment.Type.DUES, user=u, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, dues_period=dp, method=Payment.Method.OFFLINE,
        paid_at=timezone.make_aware(datetime(2023, 10, 1, 12)),
    )
    _tuition(u, "500", datetime(2023, 11, 1, 12))  # partial: $500 of $2000
    rows = {r["ay"]: r for r in survey_year_rows(u)}
    assert rows[2023]["dues_checked"] is True
    assert rows[2023]["tuition_state"] == "partial"
    assert rows[2023]["tuition_paid"] == Decimal("500")


# ---- tuition reconciliation (3-state) -------------------------------------

def test_full_no_record_is_self_reported():
    tp, _ = _periods(2023)
    u = _member()
    _apply(u, {"2023": {"tuition": "full"}})
    e = TuitionEnrollment.objects.get(user=u, tuition_period=tp)
    assert e.status == TuitionEnrollment.Status.PAID_IN_FULL
    assert e.source == Source.SELF_REPORTED


def test_partial_is_payment_plan():
    tp, _ = _periods(2023)
    u = _member()
    _apply(u, {"2023": {"tuition": "partial"}})
    e = TuitionEnrollment.objects.get(user=u, tuition_period=tp)
    assert e.status == TuitionEnrollment.Status.PAYMENT_PLAN
    assert e.source == Source.SELF_REPORTED


def test_full_with_record_is_verified():
    tp, _ = _periods(2023)
    u = _member()
    _tuition(u, "2000", datetime(2023, 10, 1, 12))
    _apply(u, {"2023": {"tuition": "full"}})
    e = TuitionEnrollment.objects.get(user=u, tuition_period=tp)
    assert e.source == Source.VERIFIED


def test_unmarked_current_student_is_skipping():
    tp, _ = _periods(2023)
    u = _member(role=Profile.Role.CANDIDATE)
    _apply(u, {"2023": {"tuition": ""}}, year_joined=2020)
    e = TuitionEnrollment.objects.get(user=u, tuition_period=tp)
    assert e.status == TuitionEnrollment.Status.SKIPPING


def test_unmarked_with_payment_not_skipped():
    tp, _ = _periods(2023)
    u = _member()
    _tuition(u, "2000", datetime(2023, 10, 1, 12))
    _apply(u, {"2023": {"tuition": ""}})
    assert not TuitionEnrollment.objects.filter(
        user=u, status=TuitionEnrollment.Status.SKIPPING
    ).exists()


# ---- dues -----------------------------------------------------------------

def test_dues_no_record_self_reported_estimate():
    tp, dp = _periods(2023)
    u = _member(role=Profile.Role.CANDIDATE)
    _apply(u, {"2023": {"dues": True}})
    p = Payment.objects.get(user=u, payment_type=Payment.Type.DUES, dues_period=dp)
    assert p.source == Source.SELF_REPORTED
    assert p.amount == Decimal("100")


def test_dues_with_record_is_verified():
    tp, dp = _periods(2023)
    u = _member()
    existing = Payment.objects.create(
        payment_type=Payment.Type.DUES, user=u, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, dues_period=dp, method=Payment.Method.OFFLINE,
        source=Source.IMPORTED, paid_at=timezone.make_aware(datetime(2023, 10, 1, 12)),
    )
    _apply(u, {"2023": {"dues": True}})
    existing.refresh_from_db()
    assert existing.source == Source.VERIFIED


# ---- milestones → tenure chain --------------------------------------------

def test_milestone_questions_by_role():
    u = _member(role=Profile.Role.ANALYST)
    keys = [m["key"] for m in milestone_questions(u)]
    assert keys == ["palimpsest", "passage"]
    s = _member("sch@x.test", role=Profile.Role.SCHOLAR)
    assert [m["key"] for m in milestone_questions(s)] == ["palimpsest", "traversee"]
    c = _member("cand@x.test", role=Profile.Role.CANDIDATE)
    assert [m["key"] for m in milestone_questions(c)] == ["palimpsest"]


def test_milestones_build_tenure_chain():
    u = _member(role=Profile.Role.ANALYST)
    _apply(u, {}, year_joined=2017,
           milestones={"palimpsest": 2019, "passage": 2023})
    tenures = list(MembershipTenure.objects.filter(user=u).order_by("start_ay"))
    assert [(t.role, t.start_ay, t.end_ay) for t in tenures] == [
        (Profile.Role.PRE_CANDIDATE, 2017, 2018),
        (Profile.Role.CANDIDATE, 2019, 2022),
        (Profile.Role.ANALYST, 2023, None),
    ]


def test_tenure_chain_not_clobbering_authoritative():
    u = _member(role=Profile.Role.ANALYST)
    MembershipTenure.objects.create(
        user=u, role=Profile.Role.ANALYST, start_ay=2015, source=Source.STAFF,
    )
    _apply(u, {}, year_joined=2010, milestones={"palimpsest": 2012})
    # Authoritative (staff) history present → survey leaves it alone.
    assert MembershipTenure.objects.filter(user=u).count() == 1
    assert MembershipTenure.objects.get(user=u).source == Source.STAFF


# ---- idempotency ----------------------------------------------------------

def test_apply_is_idempotent():
    _periods(2023)
    u = _member()
    _apply(u, {"2023": {"tuition": "full", "dues": True}}, year_joined=2019,
           milestones={"palimpsest": 2021})
    _apply(u, {"2023": {"tuition": "full", "dues": True}}, year_joined=2019,
           milestones={"palimpsest": 2021})
    assert TuitionEnrollment.objects.filter(user=u).count() == 1
    assert Payment.objects.filter(user=u, payment_type=Payment.Type.DUES).count() == 1
    assert MemberIntakeSurvey.objects.filter(user=u).count() == 1


# ---- view + advisor + nudge -----------------------------------------------

def test_survey_requires_login(client):
    assert client.get(reverse("intake_survey")).status_code == 302


def test_survey_get_and_post(client):
    _periods(2023)
    u = _member()
    client.force_login(u)
    assert client.get(reverse("intake_survey")).status_code == 200
    resp = client.post(reverse("intake_survey"), {
        "year_joined": "2020", "tuition_2023": "full", "dues_2023": "on",
        "milestone_palimpsest": "2021",
    })
    assert resp.status_code == 302
    s = MemberIntakeSurvey.objects.get(user=u)
    assert s.grid == {"2023": {"tuition": "full", "dues": True}}
    assert s.milestones == {"palimpsest": 2021}


def test_survey_sets_advisor(client):
    _periods(2023)
    from accounts.advisor import current_advisor
    u = _member(role=Profile.Role.CANDIDATE)
    analyst = _member("an@x.test", role=Profile.Role.ANALYST)
    analyst.profile.standing = Profile.Standing.ACTIVE
    analyst.profile.save()
    client.force_login(u)
    client.post(reverse("intake_survey"), {
        "year_joined": "2020", "advisor": str(analyst.pk),
    })
    assert current_advisor(u) == analyst


@override_settings(SURVEY_ENABLED=True)
def test_nudge_shows_until_submitted(client):
    u = _member()
    client.force_login(u)
    assert b"intake survey" in client.get(reverse("core:landing")).content.lower()
    MemberIntakeSurvey.objects.create(user=u, submitted_at=timezone.now())
    assert b"start the survey" not in client.get(reverse("core:landing")).content.lower()
