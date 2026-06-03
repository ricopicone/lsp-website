"""Tests for the historical period seeder."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.core.management import call_command

from payments.models import DuesPeriod, TuitionPeriod

pytestmark = pytest.mark.django_db

D22 = datetime.date(2022, 9, 1)
D23 = datetime.date(2023, 9, 1)
D24 = datetime.date(2024, 9, 1)


def test_dry_run_writes_nothing():
    call_command("seed_historical_periods", "--from-ay", "2022", "--through-ay", "2023")
    assert not DuesPeriod.objects.filter(start_date=D22).exists()
    assert not TuitionPeriod.objects.filter(start_date=D22).exists()


def test_commit_creates_periods():
    call_command("seed_historical_periods", "--from-ay", "2022", "--through-ay",
                 "2024", "--commit")
    tp = TuitionPeriod.objects.get(start_date=D22)
    assert tp.tuition_amount == Decimal("2000")
    assert tp.end_date == datetime.date(2023, 8, 31)
    dp = DuesPeriod.objects.get(start_date=D23)
    assert (dp.dues_amount_pre_candidate, dp.dues_amount_candidate,
            dp.dues_amount_analyst) == (Decimal("50"), Decimal("100"), Decimal("150"))


def test_idempotent_leaves_existing():
    DuesPeriod.objects.create(
        name="AY 2024–2025", slug="ay-2024-2025",
        start_date=D24, end_date=datetime.date(2025, 8, 31),
        due_date=datetime.date(2024, 12, 1),
        dues_amount_pre_candidate=Decimal("99"),
        dues_amount_candidate=Decimal("99"), dues_amount_analyst=Decimal("99"),
    )
    call_command("seed_historical_periods", "--from-ay", "2024", "--through-ay",
                 "2024", "--commit")
    # The pre-existing dues row is untouched; only the missing tuition row is added.
    assert DuesPeriod.objects.get(start_date=D24).dues_amount_analyst == Decimal("99")
    assert TuitionPeriod.objects.filter(start_date=D24).exists()
