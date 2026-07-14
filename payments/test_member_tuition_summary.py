"""Per-AY tuition summary on the treasurer member page: paid-vs-owed, honest
attribution (link wins, else payment date), over/short flags. (Task #435.)"""

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


def _tuition(user, amount, when, **extra):
    p = Payment.objects.create(
        user=user, payment_type=Payment.Type.TUITION, amount=amount,
        status=Payment.Status.SUCCEEDED, method=Payment.Method.STRIPE, **extra)
    Payment.objects.filter(pk=p.pk).update(paid_at=when)
    p.refresh_from_db()
    return p


@pytest.mark.django_db
def test_link_wins_and_date_attributes_the_rest(member):
    ay = _period("AY 2025–2026", "ay-2526", date(2025, 9, 1), date(2026, 8, 31), Decimal("2500"))
    enr = TuitionEnrollment.objects.create(
        user=member, tuition_period=ay, status=TuitionEnrollment.Status.PAID_IN_FULL,
        source="staff")
    i1 = TuitionInstallment.objects.create(enrollment=enr, sequence=1, amount=Decimal("1000"),
                                           due_date=date(2026, 1, 3), paid=True)
    i2 = TuitionInstallment.objects.create(enrollment=enr, sequence=2, amount=Decimal("500"),
                                           due_date=date(2026, 2, 3), paid=True)
    # Installment-linked payments (link decides the year).
    _tuition(member, "1000", datetime(2026, 1, 3, 12, tzinfo=tz.utc), tuition_installment=i1)
    _tuition(member, "500", datetime(2026, 2, 3, 12, tzinfo=tz.utc), tuition_installment=i2)
    # Unlinked lump — attributed to 2025–26 by its date (May 2026 is in the AY window).
    _tuition(member, "2500", datetime(2026, 5, 22, 12, tzinfo=tz.utc))

    summary = _member_tuition_summary(member)
    row = next(r for r in summary["rows"] if r["period"].id == ay.id)
    assert row["owed"] == Decimal("2500")
    assert row["paid"] == Decimal("4000")        # 1000 + 500 + 2500
    assert len(row["payments"]) == 3             # the lump is now visible
    assert row["overpaid"] is True               # 4000 > 2500 flagged


@pytest.mark.django_db
def test_marked_paid_in_full_but_short_is_flagged(member):
    ay = _period("AY 2024–2025", "ay-2425", date(2024, 9, 1), date(2025, 8, 31), Decimal("2000"))
    TuitionEnrollment.objects.create(
        user=member, tuition_period=ay, status=TuitionEnrollment.Status.PAID_IN_FULL,
        source="staff")
    _tuition(member, "500", datetime(2024, 10, 1, 12, tzinfo=tz.utc))  # only 500 of 2000
    summary = _member_tuition_summary(member)
    row = next(r for r in summary["rows"] if r["period"].id == ay.id)
    assert row["paid"] == Decimal("500")
    assert row["short"] is True                  # marked paid-in-full but under


@pytest.mark.django_db
def test_payment_outside_any_period_is_unattributed(member):
    _period("AY 2025–2026", "ay-2526", date(2025, 9, 1), date(2026, 8, 31), Decimal("2500"))
    _tuition(member, "300", datetime(2019, 1, 1, 12, tzinfo=tz.utc))  # no period covers 2019
    summary = _member_tuition_summary(member)
    assert any(p.amount == Decimal("300") for p in summary["unattributed"])
