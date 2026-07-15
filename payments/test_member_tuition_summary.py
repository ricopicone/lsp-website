"""Tuition as a cumulative ledger on the treasurer member page: obligation-to-date
(non-skipped enrolled years) vs total paid, per-year decisions, conflict flag. (#437)

Ported onto the unified ledger (task #439): ``ledger.member_account`` replaces
``_member_tuition_summary``. Fixtures create only tuition enrollments/payments
(no dues/registration charges), so ``member_account``'s all-category
``obligation``/``paid``/``balance`` numbers are identical to the old
tuition-only figures. Enrollment saves mint the underlying Charge rows via the
post_save signal (payments/signals.py)."""

from datetime import date, datetime
from datetime import timezone as tz
from decimal import Decimal

import pytest

from accounts.models import User
from payments import ledger
from payments.models import Charge, Payment, TuitionEnrollment, TuitionPeriod

pytestmark = pytest.mark.django_db


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


def _paying_years(member) -> int:
    """Count of OPEN tuition charges — the new-model equivalent of the old
    "paying_years" figure (each owed, non-skipping year mints exactly one
    charge; sync voids the rest)."""
    return Charge.objects.filter(
        user=member, category=Charge.Category.TUITION,
        status=Charge.Status.OPEN,
    ).count()


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


def test_obligation_excludes_skipping(member):
    _matt(member)
    acct = ledger.member_account(member)
    assert acct["obligation"] == Decimal("6000")   # 3 non-skipping years, not 8500
    assert _paying_years(member) == 3
    assert sum(1 for r in acct["tuition_rows"] if r["state"] == "skipping") == 1


def test_credit_and_conflict_when_paid_past_obligation_with_a_skipping_year(member):
    _matt(member)
    acct = ledger.member_account(member)
    assert acct["total_tuition_paid"] == Decimal("7500")
    assert acct["balance"] == Decimal("-1500")     # paid past obligation
    assert acct["credit"] == Decimal("1500")
    assert acct["owes"] == Decimal("0")
    assert acct["conflict"] is True                # skipping year + credit → review


def test_owes_when_all_years_paying(member):
    _matt(member)
    # Correct the bad "skipping" to paying → obligation jumps, he actually owes.
    enr = TuitionEnrollment.objects.get(user=member, tuition_period__slug="d")
    enr.status = TuitionEnrollment.Status.COMMITTED
    enr.save()
    acct = ledger.member_account(member)
    assert acct["obligation"] == Decimal("8500")
    assert acct["owes"] == Decimal("1000")         # $7500 of $8500
    assert acct["credit"] == Decimal("0")
    assert acct["conflict"] is False


def test_no_conflict_when_overpaid_without_skipping(member):
    p = _period("AY 2025-2026", "d", date(2025, 9, 1), date(2026, 8, 31), Decimal("2000"))
    _enroll(member, p, TuitionEnrollment.Status.PAID_IN_FULL)
    _tuition(member, "2500", datetime(2026, 1, 1, 12, tzinfo=tz.utc))  # genuine overpay
    acct = ledger.member_account(member)
    assert acct["credit"] == Decimal("500")
    assert acct["conflict"] is False               # no skipping year → real credit


def test_rows_carry_coverage_state_not_dollar_allocation(member):
    _matt(member)
    acct = ledger.member_account(member)
    # Per-year rows expose a derived coverage state + rate; no per-year dollars.
    row = acct["tuition_rows"][0]
    assert "state" in row and "rate" in row
    assert "applied" not in row and "balance" not in row


def test_coverage_fills_oldest_year_first(member):
    p22 = _period("AY 2022-2023", "a", date(2022, 9, 1), date(2023, 8, 31), Decimal("2000"))
    p23 = _period("AY 2023-2024", "b", date(2023, 9, 1), date(2024, 8, 31), Decimal("2000"))
    p24 = _period("AY 2024-2025", "c", date(2024, 9, 1), date(2025, 8, 31), Decimal("2000"))
    for p in (p22, p23, p24):
        _enroll(member, p, TuitionEnrollment.Status.COMMITTED)
    _tuition(member, "5000", datetime(2025, 1, 1, 12, tzinfo=tz.utc))  # covers 2.5 years
    acct = ledger.member_account(member)
    by_year = {r["period"].slug: r["state"] for r in acct["tuition_rows"]}
    assert by_year["a"] == "paid"      # oldest cleared first
    assert by_year["b"] == "paid"
    assert by_year["c"] == "partial"   # the remainder lands here


def test_obligation_caps_at_four_years(member):
    # Five enrolled, non-skipping years — but tuition is 4 years total.
    for yr in (2021, 2022, 2023, 2024, 2025):
        p = _period(f"AY {yr}", f"y{yr}", date(yr, 9, 1), date(yr + 1, 8, 31), Decimal("2000"))
        _enroll(member, p, TuitionEnrollment.Status.PAID_IN_FULL)
    _tuition(member, "8000", datetime(2025, 1, 1, 12, tzinfo=tz.utc))  # exactly 4 years

    acct = ledger.member_account(member)
    assert acct["obligation"] == Decimal("8000")   # 4 years, never 5
    assert _paying_years(member) == 4
    assert acct["owes"] == Decimal("0")            # paid up on the 4 owed years
    # The 5th (newest) year is "requirement met", not owed.
    newest = next(r for r in acct["tuition_rows"] if r["period"].slug == "y2025")
    assert newest["state"] == "met"


def test_matt_all_paying_years_show_covered(member):
    _matt(member)
    acct = ledger.member_account(member)
    states = {r["period"].slug: r["state"] for r in acct["tuition_rows"]}
    assert states["a"] == "paid" and states["b"] == "paid" and states["c"] == "paid"
    assert states["d"] == "skipping"
