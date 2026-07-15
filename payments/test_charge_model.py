"""Charge — the debit row of the unified member ledger (task #439)."""

from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError

from accounts.models import User
from payments.models import Charge, DuesPeriod

pytestmark = pytest.mark.django_db


@pytest.fixture
def member():
    return User.objects.create_user(email="ch@x.test", password="x")


@pytest.fixture
def period():
    DuesPeriod.objects.all().delete()
    return DuesPeriod.objects.create(
        name="AY 2026-2027", slug="ay-2026-2027",
        start_date=date(2026, 9, 1), due_date=date(2026, 9, 30),
        end_date=date(2027, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"),
    )


def test_defaults(member, period):
    c = Charge.objects.create(
        user=member, category=Charge.Category.DUES, amount=Decimal("100"),
        effective_date=period.start_date, dues_period=period,
    )
    assert c.status == Charge.Status.OPEN
    assert c.staff_adjusted is False
    assert c.currency == "usd"


def test_one_open_dues_charge_per_period(member, period):
    Charge.objects.create(
        user=member, category=Charge.Category.DUES, amount=Decimal("100"),
        effective_date=period.start_date, dues_period=period,
    )
    with pytest.raises(IntegrityError):
        Charge.objects.create(
            user=member, category=Charge.Category.DUES, amount=Decimal("100"),
            effective_date=period.start_date, dues_period=period,
        )


def test_void_rows_do_not_block_a_replacement(member, period):
    Charge.objects.create(
        user=member, category=Charge.Category.DUES, amount=Decimal("100"),
        effective_date=period.start_date, dues_period=period,
        status=Charge.Status.VOID,
    )
    # A VOID row is out of the books — a fresh OPEN row is allowed.
    Charge.objects.create(
        user=member, category=Charge.Category.DUES, amount=Decimal("100"),
        effective_date=period.start_date, dues_period=period,
    )


def test_add_note_appends_dated_line(member, period):
    c = Charge.objects.create(
        user=member, category=Charge.Category.DUES, amount=Decimal("100"),
        effective_date=period.start_date, dues_period=period,
    )
    c.add_note("Waived by treasurer t@x.test.")
    c.refresh_from_db()
    assert "Waived by treasurer t@x.test." in c.notes
    c.add_note("Second line.")
    c.refresh_from_db()
    assert c.notes.count("\n") == 1
