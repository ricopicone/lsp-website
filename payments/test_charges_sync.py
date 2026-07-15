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
