"""Per-AY tuition balance on the treasurer member page: oldest-unpaid-first
waterfall, tied payments win, running total + credit. (Tasks #435, #437.)"""

from datetime import date, datetime
from datetime import timezone as tz
from decimal import Decimal

import pytest

from accounts.models import User
from payments.models import (
    Payment,
    TuitionEnrollment,
    TuitionInstallment,
    TuitionPeriod,
)
from payments.views import _member_tuition_summary


@pytest.fixture
def member(db):
    # The seed migration pre-populates TuitionPeriods; start from a clean slate.
    TuitionPeriod.objects.all().delete()
    return User.objects.create_user(email="mt@x.test", password="x")


def _period(name, slug, s, e, amt):
    return TuitionPeriod.objects.create(
        name=name, slug=slug, start_date=s, end_date=e, tuition_amount=amt,
        decision_due_date=s)


def _enroll(user, period, status=TuitionEnrollment.Status.COMMITTED):
    return TuitionEnrollment.objects.create(
        user=user, tuition_period=period, status=status, source="staff")


def _tuition(user, amount, when, **extra):
    p = Payment.objects.create(
        user=user, payment_type=Payment.Type.TUITION, amount=amount,
        status=Payment.Status.SUCCEEDED, method=Payment.Method.STRIPE, **extra)
    Payment.objects.filter(pk=p.pk).update(paid_at=when)
    p.refresh_from_db()
    return p


def _row(summary, period):
    return next(r for r in summary["rows"] if r["period"].id == period.id)


@pytest.mark.django_db
def test_untied_payment_waterfalls_to_oldest_unpaid_first(member):
    older = _period("AY 2024–2025", "ay-2425", date(2024, 9, 1), date(2025, 8, 31), Decimal("2000"))
    newer = _period("AY 2025–2026", "ay-2526", date(2025, 9, 1), date(2026, 8, 31), Decimal("2500"))
    _enroll(member, older)
    _enroll(member, newer)
    # One untied $3000 payment made in 2026 — still clears the OLDER year first.
    _tuition(member, "3000", datetime(2026, 5, 1, 12, tzinfo=tz.utc))

    s = _member_tuition_summary(member)
    assert _row(s, older)["applied"] == Decimal("2000")   # cleared first
    assert _row(s, older)["balance"] == Decimal("0")
    assert _row(s, newer)["applied"] == Decimal("1000")   # remainder
    assert _row(s, newer)["balance"] == Decimal("1500")
    assert _row(s, older)["state"] == "paid"
    assert _row(s, newer)["state"] == "partial"
    assert s["total_owed"] == Decimal("4500")
    assert s["net_balance"] == Decimal("1500")            # still owed
    assert s["credit"] == Decimal("0")


@pytest.mark.django_db
def test_tied_payment_stays_on_its_year(member):
    older = _period("AY 2024–2025", "ay-2425", date(2024, 9, 1), date(2025, 8, 31), Decimal("2000"))
    newer = _period("AY 2025–2026", "ay-2526", date(2025, 9, 1), date(2026, 8, 31), Decimal("2500"))
    _enroll(member, older)
    enr = _enroll(member, newer)
    inst = TuitionInstallment.objects.create(
        enrollment=enr, sequence=1, amount=Decimal("2500"), due_date=date(2026, 1, 1), paid=True)
    # tied to newer year via the installment
    _tuition(member, "2500", datetime(2026, 1, 1, 12, tzinfo=tz.utc), tuition_installment=inst)
    _tuition(member, "2000", datetime(2026, 6, 1, 12, tzinfo=tz.utc))  # untied -> older

    s = _member_tuition_summary(member)
    assert _row(s, newer)["applied"] == Decimal("2500")   # the tie held, not oldest-first
    assert _row(s, newer)["balance"] == Decimal("0")
    assert _row(s, older)["applied"] == Decimal("2000")
    assert s["net_balance"] == Decimal("0")


@pytest.mark.django_db
def test_overpayment_becomes_credit(member):
    ay = _period("AY 2025–2026", "ay-2526", date(2025, 9, 1), date(2026, 8, 31), Decimal("2500"))
    _enroll(member, ay, status=TuitionEnrollment.Status.PAID_IN_FULL)
    _tuition(member, "1500", datetime(2026, 1, 3, 12, tzinfo=tz.utc))
    _tuition(member, "2500", datetime(2026, 5, 22, 12, tzinfo=tz.utc))  # 4000 total for 2500 owed

    s = _member_tuition_summary(member)
    assert _row(s, ay)["applied"] == Decimal("2500")
    assert _row(s, ay)["balance"] == Decimal("0")
    assert _row(s, ay)["state"] == "paid"
    assert s["credit"] == Decimal("1500")          # paid ahead
    assert s["net_balance"] == Decimal("-1500")    # negative = credit
    assert s["total_paid"] == Decimal("4000")


@pytest.mark.django_db
def test_paid_in_full_but_still_owing_is_flagged(member):
    ay = _period("AY 2024–2025", "ay-2425", date(2024, 9, 1), date(2025, 8, 31), Decimal("2000"))
    _enroll(member, ay, status=TuitionEnrollment.Status.PAID_IN_FULL)
    _tuition(member, "500", datetime(2024, 10, 1, 12, tzinfo=tz.utc))  # only 500 of 2000
    s = _member_tuition_summary(member)
    row = _row(s, ay)
    assert row["balance"] == Decimal("1500")
    assert row["flag"] is True


@pytest.mark.django_db
def test_skipping_year_owes_nothing(member):
    ay = _period("AY 2024–2025", "ay-2425", date(2024, 9, 1), date(2025, 8, 31), Decimal("2000"))
    _enroll(member, ay, status=TuitionEnrollment.Status.SKIPPING)
    s = _member_tuition_summary(member)
    assert _row(s, ay)["owed"] == Decimal("0")
    assert s["total_owed"] == Decimal("0")
