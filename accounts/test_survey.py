"""Tests for the member intake survey (apply + reconciliation + view + nudge)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import MemberIntakeSurvey, MembershipTenure, Profile, Source, User
from accounts.survey import apply_survey, parse_grid, survey_year_rows
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


def _apply(user, grid, *, year_joined=2020):
    return apply_survey(user, year_joined=year_joined, pronouns=None,
                        payment_names="", payment_emails="", grid=grid)


# ---- parsing & prefill -----------------------------------------------------

def test_parse_grid():
    post = {"tuition_2023": "on", "dues_2023": "on", "dues_2022": "on", "other": "x"}
    assert parse_grid(post) == {
        "2023": {"tuition": True, "dues": True}, "2022": {"dues": True},
    }


def test_year_rows_prechecks_from_records():
    tp, dp = _periods(2023)
    u = _member()
    Payment.objects.create(
        payment_type=Payment.Type.DUES, user=u, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, dues_period=dp, method=Payment.Method.OFFLINE,
        paid_at=timezone.make_aware(datetime(2023, 10, 1, 12)),
    )
    rows = {r["ay"]: r for r in survey_year_rows(u)}
    assert rows[2023]["dues_checked"] is True
    assert rows[2023]["tuition_checked"] is False


# ---- reconciliation: tuition ----------------------------------------------

def test_checked_tuition_no_record_is_self_reported():
    tp, _ = _periods(2023)
    u = _member()
    _apply(u, {"2023": {"tuition": True}})
    e = TuitionEnrollment.objects.get(user=u, tuition_period=tp)
    assert e.status == TuitionEnrollment.Status.PAID_IN_FULL
    assert e.source == Source.SELF_REPORTED


def test_checked_tuition_with_record_is_verified():
    tp, _ = _periods(2023)
    u = _member()
    Payment.objects.create(
        payment_type=Payment.Type.TUITION, user=u, amount=Decimal("2000"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.STRIPE,
        source=Source.IMPORTED, paid_at=timezone.make_aware(datetime(2023, 10, 1, 12)),
    )
    _apply(u, {"2023": {"tuition": True}})
    e = TuitionEnrollment.objects.get(user=u, tuition_period=tp)
    assert e.source == Source.VERIFIED  # member confirmed an on-record year


def test_unchecked_tuition_current_student_is_skipping():
    tp, _ = _periods(2023)
    u = _member(role=Profile.Role.CANDIDATE)
    _apply(u, {"2023": {"tuition": False}}, year_joined=2020)
    e = TuitionEnrollment.objects.get(user=u, tuition_period=tp)
    assert e.status == TuitionEnrollment.Status.SKIPPING
    assert e.source == Source.SELF_REPORTED


def test_unchecked_tuition_with_payment_is_not_skipped():
    tp, _ = _periods(2023)
    u = _member()
    Payment.objects.create(
        payment_type=Payment.Type.TUITION, user=u, amount=Decimal("2000"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.STRIPE,
        source=Source.IMPORTED, paid_at=timezone.make_aware(datetime(2023, 10, 1, 12)),
    )
    _apply(u, {"2023": {"tuition": False}})
    # The payment record wins — no SKIPPING enrollment is invented.
    assert not TuitionEnrollment.objects.filter(
        user=u, status=TuitionEnrollment.Status.SKIPPING
    ).exists()


# ---- reconciliation: dues --------------------------------------------------

def test_checked_dues_no_record_creates_self_reported_estimate():
    tp, dp = _periods(2023)
    u = _member(role=Profile.Role.CANDIDATE)
    _apply(u, {"2023": {"dues": True}})
    p = Payment.objects.get(user=u, payment_type=Payment.Type.DUES, dues_period=dp)
    assert p.source == Source.SELF_REPORTED
    assert p.amount == Decimal("100")  # candidate tier estimate
    assert p.dues_period_id == dp.id


def test_checked_dues_with_record_is_verified():
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
    assert Payment.objects.filter(user=u, payment_type=Payment.Type.DUES).count() == 1


# ---- survey row + tenure + idempotency ------------------------------------

def test_apply_seeds_tenure_and_is_idempotent():
    _periods(2023)
    u = _member()
    _apply(u, {"2023": {"tuition": True, "dues": True}}, year_joined=2019)
    assert MembershipTenure.objects.filter(user=u).count() == 1
    assert u.profile.year_joined == 2019 or User.objects.get(pk=u.pk).profile.year_joined == 2019
    # Re-apply: no duplicate rows.
    _apply(u, {"2023": {"tuition": True, "dues": True}}, year_joined=2019)
    assert TuitionEnrollment.objects.filter(user=u).count() == 1
    assert Payment.objects.filter(user=u, payment_type=Payment.Type.DUES).count() == 1
    assert MemberIntakeSurvey.objects.filter(user=u).count() == 1


# ---- view + nudge ----------------------------------------------------------

def test_survey_requires_login(client):
    assert client.get(reverse("intake_survey")).status_code == 302


def test_survey_get_and_post(client):
    tp, dp = _periods(2023)
    u = _member()
    client.force_login(u)
    assert client.get(reverse("intake_survey")).status_code == 200
    resp = client.post(reverse("intake_survey"), {
        "year_joined": "2020", "tuition_2023": "on", "dues_2023": "on",
    })
    assert resp.status_code == 302
    s = MemberIntakeSurvey.objects.get(user=u)
    assert s.submitted_at is not None
    assert s.grid == {"2023": {"tuition": True, "dues": True}}


@override_settings(SURVEY_ENABLED=True)
def test_nudge_shows_until_submitted(client):
    u = _member()
    client.force_login(u)
    assert b"intake survey" in client.get(reverse("core:landing")).content.lower()
    MemberIntakeSurvey.objects.create(user=u, submitted_at=timezone.now())
    assert b"start the survey" not in client.get(reverse("core:landing")).content.lower()


@override_settings(SURVEY_ENABLED=False)
def test_nudge_hidden_when_disabled(client):
    client.force_login(_member())
    assert b"start the survey" not in client.get(reverse("core:landing")).content.lower()
