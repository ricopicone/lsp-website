"""tuition_clearance — the promotion gate's one source of truth (task #439)."""

from datetime import date, datetime
from datetime import timezone as tz
from decimal import Decimal

import pytest

from accounts.models import User
from payments import ledger
from payments.models import Charge, DuesPeriod, Payment, TuitionEnrollment, TuitionPeriod

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_periods():
    TuitionPeriod.objects.all().delete()
    DuesPeriod.objects.all().delete()


def _candidate(email, persona=False):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = "candidate"
    u.profile.is_persona = persona
    u.profile.save()
    return u


def _year(start, amount="2000"):
    return TuitionPeriod.objects.create(
        name=f"AY {start}-{start + 1}", slug=f"t-{start}",
        start_date=date(start, 9, 1), end_date=date(start + 1, 8, 31),
        decision_due_date=date(start, 8, 31), tuition_amount=Decimal(amount))


def _enroll(u, tp, status=TuitionEnrollment.Status.COMMITTED):
    return TuitionEnrollment.objects.create(
        user=u, tuition_period=tp, status=status, source="staff")


def _pay(u, amount):
    p = Payment.objects.create(
        user=u, payment_type=Payment.Type.TUITION, amount=Decimal(amount),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE)
    Payment.objects.filter(pk=p.pk).update(
        paid_at=datetime(2025, 10, 1, tzinfo=tz.utc))


def _four_paid_years(u):
    for i in range(4):
        _enroll(u, _year(2021 + i))
    _pay(u, "8000")


def test_clear_when_four_years_covered():
    u = _candidate("cl1@x.test")
    _four_paid_years(u)
    assert ledger.tuition_clearance(u) == []


def test_uncovered_charge_blocks_with_amount():
    u = _candidate("cl2@x.test")
    for i in range(4):
        _enroll(u, _year(2021 + i))
    _pay(u, "6325")   # 3 years + $325 of the 4th
    reasons = ledger.tuition_clearance(u)
    assert any("$1675.00 uncovered" in r for r in reasons)


def test_missing_years_block():
    u = _candidate("cl3@x.test")
    for i in range(3):
        _enroll(u, _year(2021 + i))
    _pay(u, "6000")   # 3 years fully paid, no 4th enrollment
    reasons = ledger.tuition_clearance(u)
    assert reasons == ["3 of 4 tuition years covered."]


def test_waived_charge_counts_as_settled_but_not_covered():
    u = _candidate("cl4@x.test")
    for i in range(4):
        _enroll(u, _year(2021 + i))
    _pay(u, "6000")
    last = Charge.objects.filter(user=u).order_by("-effective_date").first()
    last.status = Charge.Status.WAIVED
    last.staff_adjusted = True
    last.save()
    reasons = ledger.tuition_clearance(u)
    # No "uncovered" reason (waived is settled), but only 3 years COVERED.
    assert not any("uncovered" in r for r in reasons)
    assert "3 of 4 tuition years covered." in reasons


def test_persona_always_clear():
    u = _candidate("cl5@x.test", persona=True)
    _enroll(u, _year(2021))
    assert ledger.tuition_clearance(u) == []
