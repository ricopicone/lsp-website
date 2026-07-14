"""Tuition as a cumulative ledger on the treasurer member page: obligation-to-date
(non-skipped enrolled years) vs total paid, per-year decisions, conflict flag. (#437)"""

from datetime import date, datetime
from datetime import timezone as tz
from decimal import Decimal

import pytest

from accounts.models import User
from payments.models import Payment, TuitionEnrollment, TuitionPeriod
from payments.views import _member_tuition_summary


@pytest.fixture
def member(db):
    TuitionPeriod.objects.all().delete()  # seed migration pre-populates periods
    return User.objects.create_user(email="mt@x.test", password="x")


def _period(name, slug, s, e, amt):
    return TuitionPeriod.objects.create(
        name=name, slug=slug, start_date=s, end_date=e, tuition_amount=amt,
        decision_due_date=s)


def _enroll(user, period, status):
    return TuitionEnrollment.objects.create(
        user=user, tuition_period=period, status=status, source="staff")


def _tuition(user, amount, when):
    p = Payment.objects.create(
        user=user, payment_type=Payment.Type.TUITION, amount=amount,
        status=Payment.Status.SUCCEEDED, method=Payment.Method.STRIPE)
    Payment.objects.filter(pk=p.pk).update(paid_at=when)


def _matt(member):
    """Matt Lovett's real shape: 3 paying years + a (wrong) skipping year, $7500 paid."""
    p22 = _period("AY 2022-2023", "a", date(2022, 9, 1), date(2023, 8, 31), Decimal("2000"))
    p23 = _period("AY 2023-2024", "b", date(2023, 9, 1), date(2024, 8, 31), Decimal("2000"))
    p24 = _period("AY 2024-2025", "c", date(2024, 9, 1), date(2025, 8, 31), Decimal("2000"))
    p25 = _period("AY 2025-2026", "d", date(2025, 9, 1), date(2026, 8, 31), Decimal("2500"))
    _enroll(member, p22, TuitionEnrollment.Status.PAYMENT_PLAN)
    _enroll(member, p23, TuitionEnrollment.Status.PAID_IN_FULL)
    _enroll(member, p24, TuitionEnrollment.Status.PAID_IN_FULL)
    _enroll(member, p25, TuitionEnrollment.Status.SKIPPING)
    _tuition(member, "7500", datetime(2025, 7, 16, 12, tzinfo=tz.utc))
    return p25


@pytest.mark.django_db
def test_obligation_excludes_skipping(member):
    _matt(member)
    s = _member_tuition_summary(member)
    assert s["obligation"] == Decimal("6000")   # 3 non-skipping years, not 8500
    assert s["paying_years"] == 3
    assert len(s["skipping"]) == 1


@pytest.mark.django_db
def test_credit_and_conflict_when_paid_past_obligation_with_a_skipping_year(member):
    _matt(member)
    s = _member_tuition_summary(member)
    assert s["total_paid"] == Decimal("7500")
    assert s["balance"] == Decimal("-1500")     # paid past obligation
    assert s["credit"] == Decimal("1500")
    assert s["owes"] == Decimal("0")
    assert s["conflict"] is True                # skipping year + credit → review


@pytest.mark.django_db
def test_owes_when_all_years_paying(member):
    _matt(member)
    # Correct the bad "skipping" to paying → obligation jumps, he actually owes.
    enr = TuitionEnrollment.objects.get(user=member, tuition_period__slug="d")
    enr.status = TuitionEnrollment.Status.COMMITTED
    enr.save()
    s = _member_tuition_summary(member)
    assert s["obligation"] == Decimal("8500")
    assert s["owes"] == Decimal("1000")         # $7500 of $8500
    assert s["credit"] == Decimal("0")
    assert s["conflict"] is False


@pytest.mark.django_db
def test_no_conflict_when_overpaid_without_skipping(member):
    p = _period("AY 2025-2026", "d", date(2025, 9, 1), date(2026, 8, 31), Decimal("2000"))
    _enroll(member, p, TuitionEnrollment.Status.PAID_IN_FULL)
    _tuition(member, "2500", datetime(2026, 1, 1, 12, tzinfo=tz.utc))  # genuine overpay
    s = _member_tuition_summary(member)
    assert s["credit"] == Decimal("500")
    assert s["conflict"] is False               # no skipping year → real credit


@pytest.mark.django_db
def test_rows_carry_decision_not_dollar_allocation(member):
    _matt(member)
    s = _member_tuition_summary(member)
    # Per-year rows expose the decision + rate; no per-year "paid"/"balance".
    row = s["rows"][0]
    assert "decision" in row and "rate" in row
    assert "applied" not in row and "balance" not in row
