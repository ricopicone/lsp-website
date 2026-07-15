"""Charge-minting syncs: idempotent, staff-adjusted rows untouchable (task #439)."""

from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import User
from payments import charges
from payments.models import Charge, DuesPeriod, TuitionPeriod

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_periods():
    TuitionPeriod.objects.all().delete()
    DuesPeriod.objects.all().delete()


def _member(email, role="candidate"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


def _dues_period(start_year):
    return DuesPeriod.objects.create(
        name=f"AY {start_year}-{start_year + 1}", slug=f"ay-{start_year}-{start_year + 1}",
        start_date=date(start_year, 9, 1), due_date=date(start_year, 9, 30),
        end_date=date(start_year + 1, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"),
    )


def test_sync_dues_charges_mints_tiered_amounts_once():
    year = timezone.now().date().year - 1
    p = _dues_period(year)
    cand = _member("c@x.test", "candidate")
    an = _member("a@x.test", "analyst")
    assert charges.sync_dues_charges(p) == 2
    assert Charge.objects.get(user=cand).amount == Decimal("100")
    assert Charge.objects.get(user=an).amount == Decimal("150")
    assert charges.sync_dues_charges(p) == 0  # idempotent


def test_sync_dues_charges_skips_future_periods():
    p = _dues_period(timezone.now().date().year + 2)
    _member("f@x.test")
    assert charges.sync_dues_charges(p) == 0
    assert Charge.objects.count() == 0


def test_sync_dues_charges_skips_non_obligated_roles():
    year = timezone.now().date().year - 1
    p = _dues_period(year)
    _member("m@x.test", "member")  # not in DUES_OBLIGATED_ROLES
    assert charges.sync_dues_charges(p) == 0


def _tuition_period(start_year, amount="2000"):
    return TuitionPeriod.objects.create(
        name=f"AY {start_year}-{start_year + 1} T", slug=f"t-{start_year}",
        start_date=date(start_year, 9, 1), end_date=date(start_year + 1, 8, 31),
        decision_due_date=date(start_year, 8, 31), tuition_amount=Decimal(amount),
    )


def _enroll(user, period, status):
    from payments.models import TuitionEnrollment
    return TuitionEnrollment.objects.create(
        user=user, tuition_period=period, status=status, source="staff")


def test_enrollment_save_mints_a_tuition_charge():
    u = _member("t1@x.test")
    tp = _tuition_period(2026)
    _enroll(u, tp, "committed")  # signal fires
    c = Charge.objects.get(user=u, category=Charge.Category.TUITION)
    assert c.amount == Decimal("2000")
    assert c.tuition_period_id == tp.id
    assert c.status == Charge.Status.OPEN


def test_flip_to_skipping_voids_and_back_revives():
    u = _member("t2@x.test")
    tp = _tuition_period(2026)
    e = _enroll(u, tp, "committed")
    c = Charge.objects.get(user=u, category=Charge.Category.TUITION)
    e.status = "skipping"
    e.save()
    c.refresh_from_db()
    assert c.status == Charge.Status.VOID
    e.status = "committed"
    e.save()
    c.refresh_from_db()
    assert c.status == Charge.Status.OPEN
    assert Charge.objects.filter(user=u).count() == 1  # revived, not duplicated


def test_cap_mints_only_first_four_non_skipping_years():
    u = _member("t3@x.test")
    periods = [_tuition_period(2020 + i) for i in range(5)]
    for tp in periods:
        _enroll(u, tp, "committed")
    open_tp_ids = set(
        Charge.objects.filter(user=u, status=Charge.Status.OPEN)
        .values_list("tuition_period_id", flat=True)
    )
    assert open_tp_ids == {tp.id for tp in periods[:4]}  # 5th year never owed


def test_skipping_year_pulls_next_year_into_the_cap():
    u = _member("t4@x.test")
    periods = [_tuition_period(2020 + i) for i in range(5)]
    enrs = [_enroll(u, tp, "committed") for tp in periods]
    enrs[0].status = "skipping"
    enrs[0].save()
    open_tp_ids = set(
        Charge.objects.filter(user=u, status=Charge.Status.OPEN)
        .values_list("tuition_period_id", flat=True)
    )
    assert open_tp_ids == {tp.id for tp in periods[1:5]}


def test_sync_never_touches_staff_adjusted_rows():
    u = _member("t5@x.test")
    tp = _tuition_period(2026)
    e = _enroll(u, tp, "committed")
    c = Charge.objects.get(user=u)
    c.amount = Decimal("1200")            # treasurer adjusted the amount
    c.staff_adjusted = True
    c.save()
    e.status = "skipping"   # sync would normally VOID
    e.save()
    c.refresh_from_db()
    assert c.status == Charge.Status.OPEN          # untouched
    assert c.amount == Decimal("1200")
    conflicts = charges.tuition_charge_conflicts()
    assert len(conflicts) == 1
    assert conflicts[0]["charge"].id == c.id
    problem_lower = conflicts[0]["problem"].lower()
    assert "skip" in problem_lower or "not owed" in problem_lower


def test_conflict_when_staff_amount_differs_from_rate():
    u = _member("t6@x.test")
    tp = _tuition_period(2026)
    _enroll(u, tp, "committed")
    c = Charge.objects.get(user=u)
    c.amount = Decimal("999")
    c.staff_adjusted = True
    c.save()
    conflicts = charges.tuition_charge_conflicts()
    assert len(conflicts) == 1
    assert conflicts[0]["expected_rate"] == Decimal("2000")


def test_rate_change_updates_sync_managed_charge():
    u = _member("t7@x.test")
    tp = _tuition_period(2026)
    _enroll(u, tp, "committed")
    tp.tuition_amount = Decimal("2500")
    tp.save()
    charges.sync_tuition_charges(u)
    assert Charge.objects.get(user=u).amount == Decimal("2500")
