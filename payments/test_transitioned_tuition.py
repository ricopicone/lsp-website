"""Transitioned members (Analyst/Scholar) owe no tuition: history freezes at
transition, and the one-time reconstruction trims charges to recorded
payments (task #439 follow-up)."""

from datetime import date, datetime
from datetime import timezone as tz
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from accounts.models import User
from payments import charges
from payments.models import Charge, DuesPeriod, Payment, TuitionEnrollment, TuitionPeriod

pytestmark = pytest.mark.django_db

WHEN = datetime(2024, 10, 1, 12, tzinfo=tz.utc)


@pytest.fixture(autouse=True)
def _clean_periods():
    TuitionPeriod.objects.all().delete()
    DuesPeriod.objects.all().delete()


def _member(email, role="candidate"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


def _period(start_year, amount="2000"):
    return TuitionPeriod.objects.create(
        name=f"AY {start_year}-{start_year + 1} T", slug=f"t-{start_year}",
        start_date=date(start_year, 9, 1), end_date=date(start_year + 1, 8, 31),
        decision_due_date=date(start_year, 8, 31), tuition_amount=Decimal(amount),
    )


def _enroll(user, period, status=TuitionEnrollment.Status.COMMITTED):
    return TuitionEnrollment.objects.create(
        user=user, tuition_period=period, status=status, source="assumed")


def _pay_tuition(user, amount, when=WHEN):
    p = Payment.objects.create(
        user=user, payment_type=Payment.Type.TUITION, amount=Decimal(amount),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE)
    Payment.objects.filter(pk=p.pk).update(paid_at=when)
    return p


def _transition(user, role="analyst"):
    user.profile.role = role
    user.profile.save()


def _run(*args):
    out = StringIO()
    call_command("reconcile_transitioned_tuition", *args, stdout=out)
    return out.getvalue()


# --- Freeze rule -----------------------------------------------------------

def test_sync_mints_nothing_for_non_in_training():
    u = _member("fz1@x.test", role="analyst")
    tp = _period(2023)
    _enroll(u, tp)  # signal fires, but history is frozen
    assert Charge.objects.filter(user=u).count() == 0


def test_sync_does_not_void_or_revive_frozen_history():
    u = _member("fz2@x.test")
    tp = _period(2023)
    e = _enroll(u, tp)
    c = Charge.objects.get(user=u)
    _transition(u)
    e.status = TuitionEnrollment.Status.SKIPPING
    e.save()  # would void for a student; frozen for an analyst
    c.refresh_from_db()
    assert c.status == Charge.Status.OPEN
    charges.sync_tuition_charges(u)  # explicit call also a no-op
    c.refresh_from_db()
    assert c.status == Charge.Status.OPEN


def test_conflicts_skip_non_in_training_members():
    u = _member("fz3@x.test")
    tp = _period(2023)
    _enroll(u, tp)
    c = Charge.objects.get(user=u)
    c.status = Charge.Status.VOID
    c.staff_adjusted = True
    c.save()
    assert len(charges.tuition_charge_conflicts()) == 1  # student: real conflict
    _transition(u)
    assert charges.tuition_charge_conflicts() == []      # analyst: frozen


# --- Reconstruction command ------------------------------------------------

def _analyst_with_history(email, years_amounts, paid):
    """Enroll + mint while a candidate, then transition to Analyst."""
    u = _member(email)
    for start_year, amount in years_amounts:
        _enroll(u, _period(start_year, amount))
    if Decimal(paid) > 0:
        _pay_tuition(u, paid)
    _transition(u)
    return u


def test_fully_covered_charges_are_kept():
    u = _analyst_with_history("rc1@x.test", [(2022, "2000"), (2023, "2000")], "4000")
    _run()
    states = list(Charge.objects.filter(user=u).values_list("status", "amount"))
    assert states == [("open", Decimal("2000")), ("open", Decimal("2000"))]
    assert not Charge.objects.filter(user=u, staff_adjusted=True).exists()


def test_partial_charge_trimmed_to_covered_amount():
    u = _analyst_with_history("rc2@x.test", [(2023, "2000")], "325")
    _run()
    c = Charge.objects.get(user=u)
    assert c.status == Charge.Status.OPEN
    assert c.amount == Decimal("325")
    assert c.staff_adjusted is True
    assert "completed before records" in c.notes


def test_uncovered_charge_voided():
    u = _analyst_with_history("rc3@x.test", [(2022, "2000"), (2023, "2000")], "2000")
    _run()
    by_year = {c.tuition_period.slug: c for c in
               Charge.objects.filter(user=u).select_related("tuition_period")}
    assert by_year["t-2022"].status == Charge.Status.OPEN      # oldest covered
    assert by_year["t-2023"].status == Charge.Status.VOID
    assert by_year["t-2023"].staff_adjusted is True


def test_overpaid_member_keeps_charges_and_credit_signal():
    u = _analyst_with_history("rc4@x.test", [(2023, "2000")], "8000")
    _run()
    c = Charge.objects.get(user=u)
    assert c.status == Charge.Status.OPEN and c.amount == Decimal("2000")
    from payments import ledger
    assert ledger.member_account(u)["credit"] == Decimal("6000")  # stays visible


def test_in_training_members_untouched():
    u = _member("rc5@x.test")  # still a candidate
    _enroll(u, _period(2023))
    _run()
    c = Charge.objects.get(user=u)
    assert c.status == Charge.Status.OPEN and c.amount == Decimal("2000")


def test_dry_run_writes_nothing_and_rerun_is_idempotent():
    u = _analyst_with_history("rc6@x.test", [(2023, "2000")], "325")
    out = _run("--dry-run")
    assert "dry run" in out.lower()
    assert Charge.objects.get(user=u).amount == Decimal("2000")
    _run()
    _run()  # idempotent: trimmed charge is now fully covered → kept
    c = Charge.objects.get(user=u)
    assert c.amount == Decimal("325")
    assert c.notes.count("Trimmed") == 1
