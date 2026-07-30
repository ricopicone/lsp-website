"""Coverage re-billing (task #485) — what tuition coverage bought a member in a
year, and what each of those registrations is worth if the year ends up skipped."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from accounts.models import Profile, User
from events.models import Audience, Event, PriceTier
from payments import coverage
from payments.models import TuitionPeriod
from registrations.models import Registration

pytestmark = pytest.mark.django_db


@pytest.fixture
def period():
    TuitionPeriod.objects.all().delete()   # seed migration pre-populates periods
    return TuitionPeriod.objects.create(
        name="AY 2026–2027", slug="ay-2026-2027-cov",
        start_date=date(2026, 9, 1), decision_due_date=date(2026, 10, 31),
        end_date=date(2027, 8, 31), tuition_amount=Decimal("800.00"),
    )


@pytest.fixture
def student():
    u = User.objects.create_user(email="cov-student@x.test", password="x")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.save()
    return u


def _event(slug, start=date(2026, 10, 1)):
    return Event.objects.create(
        title=slug.title(), slug=slug, start_date=start, end_date=start,
        status=Event.Status.OPEN, published=True,
    )


def _tier(event, *, amount="200.00", covered=True, sliding=False, minimum="0.00"):
    return PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal(amount),
        covered_by_tuition=covered, sliding_scale=sliding,
        minimum_amount=Decimal(minimum),
    )


def _reg(student, tier, *, status=Registration.Status.PAID, amount="0.00", code=None):
    return Registration.objects.create(
        user=student, event=tier.event, price_tier=tier, pricing_code=code,
        quoted_amount=Decimal(amount),
        quoted_explanation=coverage.COVERED_EXPLANATION,
        status=status,
    )


def test_retro_amount_is_the_listed_price_for_a_flat_tier(period):
    tier = _tier(_event("flat"), amount="200.00")
    assert coverage.retro_amount(tier) == Decimal("200.00")


def test_retro_amount_is_the_floor_for_a_sliding_tier(period):
    """A skipping member would have picked their own figure at or above the
    floor, so assume the floor rather than the top."""
    tier = _tier(_event("slide"), amount="200.00", sliding=True, minimum="60.00")
    assert coverage.retro_amount(tier) == Decimal("60.00")


def test_covered_registrations_finds_a_covered_zero_registration(period, student):
    reg = _reg(student, _tier(_event("seminar-a")))
    assert coverage.covered_registrations(student, period) == [reg]


def test_covered_registrations_excludes_another_academic_year(period, student):
    _reg(student, _tier(_event("last-year", start=date(2025, 10, 1))))
    assert coverage.covered_registrations(student, period) == []


def test_covered_registrations_excludes_a_comp(period, student):
    """A comp is already charge-backed by mint_comped_charge, and it is not
    tuition coverage."""
    _reg(student, _tier(_event("comped")), status=Registration.Status.COMPED)
    assert coverage.covered_registrations(student, period) == []


def test_covered_registrations_excludes_a_pricing_code_freebie(period, student):
    """A code that zeroed the fee is not tuition coverage. PricingCode has no
    "free" mode — 100 percent off is how a free code is expressed."""
    from events.models import PricingCode

    tier = _tier(_event("codefree"))
    code = PricingCode.objects.create(
        event=tier.event, code="FREE-1", issued_by=student,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("100"),
    )
    _reg(student, tier, code=code)
    assert coverage.covered_registrations(student, period) == []


def test_covered_registrations_excludes_a_cancelled_registration(period, student):
    _reg(student, _tier(_event("gone")), status=Registration.Status.CANCELLED)
    assert coverage.covered_registrations(student, period) == []


def test_covered_registrations_excludes_a_paid_nonzero_registration(period, student):
    """Someone who paid the regular fee owes nothing extra."""
    _reg(student, _tier(_event("paidfor")), amount="200.00")
    assert coverage.covered_registrations(student, period) == []
