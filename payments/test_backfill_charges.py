"""backfill_charges — one-time history minting, idempotent (task #439)."""

from datetime import date, datetime
from datetime import timezone as tz
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from accounts.models import User
from payments.models import Charge, DuesPeriod, Payment, TuitionEnrollment, TuitionPeriod

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_periods():
    TuitionPeriod.objects.all().delete()
    DuesPeriod.objects.all().delete()


def _dues_period(start_year):
    return DuesPeriod.objects.create(
        name=f"AY {start_year}-{start_year + 1}", slug=f"ay-{start_year}-{start_year + 1}",
        start_date=date(start_year, 9, 1), due_date=date(start_year, 9, 30),
        end_date=date(start_year + 1, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"),
    )


def _member(email, role="candidate", year_joined=None):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    if year_joined:
        u.profile.year_joined = year_joined
    u.profile.save()
    return u


def _run(*args):
    out = StringIO()
    call_command("backfill_charges", *args, stdout=out)
    return out.getvalue()


def test_dues_backfill_respects_start_and_provenance():
    _dues_period(2020)   # before the default 2021-09-01 cutoff
    _dues_period(2022)   # after
    _member("b1@x.test")
    _run()
    charges = Charge.objects.filter(category=Charge.Category.DUES)
    assert charges.count() == 1
    c = charges.get()
    assert c.dues_period.slug == "ay-2022-2023"
    assert c.source == "assumed"


def test_dues_backfill_skips_members_who_joined_later():
    _dues_period(2022)
    _member("b2@x.test", year_joined=2024)
    _run()
    assert Charge.objects.count() == 0


def test_idempotent_rerun():
    _dues_period(2022)
    _member("b3@x.test")
    _run()
    _run()
    assert Charge.objects.filter(category=Charge.Category.DUES).count() == 1


def test_pre_ledger_dues_payments_get_settlement_charges():
    old = _dues_period(2019)
    u = _member("b4@x.test")
    for amount in ("50", "50"):
        p = Payment.objects.create(
            user=u, payment_type=Payment.Type.DUES, amount=Decimal(amount),
            status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
            dues_period=old,
        )
        Payment.objects.filter(pk=p.pk).update(
            paid_at=datetime(2019, 10, 1, tzinfo=tz.utc))
    _run()
    c = Charge.objects.get(user=u, dues_period=old)
    assert c.amount == Decimal("100")          # summed, one row per period
    assert c.source == "imported"


def test_tuition_and_registration_passes_mint():
    tp = TuitionPeriod.objects.create(
        name="AY 2025-2026 T", slug="t-2025", start_date=date(2025, 9, 1),
        end_date=date(2026, 8, 31), decision_due_date=date(2025, 8, 31),
        tuition_amount=Decimal("2000"))
    u = _member("b5@x.test")
    # Bypass the signal to simulate pre-existing rows: create, then delete
    # the minted charge so only the backfill pass can restore it.
    TuitionEnrollment.objects.create(
        user=u, tuition_period=tp, status=TuitionEnrollment.Status.COMMITTED,
        source="staff")
    Charge.objects.all().delete()
    _run()
    assert Charge.objects.filter(
        user=u, category=Charge.Category.TUITION, status=Charge.Status.OPEN,
    ).count() == 1


def test_dry_run_writes_nothing():
    _dues_period(2022)
    _member("b6@x.test")
    out = _run("--dry-run")
    assert Charge.objects.count() == 0
    assert "dry run" in out.lower()
