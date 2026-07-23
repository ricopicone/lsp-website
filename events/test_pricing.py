"""Tests for the pricing resolver (architecture § 6.2)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import User
from events.models import Audience, Event, PriceTier, PricingCode
from events.pricing import PriceResolution, PricingError, resolve_price


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="X", slug="x",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )


@pytest.fixture
def faculty(db):
    user = User.objects.create_user(email="fac@example.com")
    user.profile.is_faculty = True
    user.profile.save()
    return user


@pytest.fixture
def tuition_period_2026(db):
    """The TuitionPeriod covering the `event` fixture's AY (Sept 2026-Aug
    2027). Coverage is event-anchored (task #450 phase A), so a decision
    must be recorded against *this* period, not whatever
    TuitionPeriod.current() happens to be on the day tests run."""
    from payments.models import TuitionPeriod

    return TuitionPeriod.objects.create(
        name="AY 2026–2027", slug="ay-2026-2027-test",
        start_date=date(2026, 9, 1), decision_due_date=date(2026, 10, 31),
        end_date=date(2027, 8, 31), tuition_amount=Decimal("800.00"),
    )


@pytest.fixture
def tuition_member(db, tuition_period_2026):
    """A user with a tuition enrollment (status=committed) against the
    `event` fixture's AY (Sept 2026-Aug 2027).

    A TuitionEnrollment row is the source of truth for "is this member
    tuition-paying this year?" — drives the REG-4 covered-by-tuition path.
    """
    from payments.models import TuitionEnrollment

    user = User.objects.create_user(email="tm@example.com")
    TuitionEnrollment.objects.update_or_create(
        user=user, tuition_period=tuition_period_2026,
        defaults={"status": TuitionEnrollment.Status.COMMITTED},
    )
    return user


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(email="reg@example.com")


# --- Standard, covered-by-tuition, sliding scale ------------------------


def test_standard_base_amount(event, regular_user):
    tier = PriceTier.objects.create(
        event=event, audience=Audience.STUDENT, base_amount=Decimal("100.00")
    )
    result = resolve_price(user=regular_user, tier=tier)
    assert result.amount == Decimal("100.00")
    assert "Standard" in result.explanation
    assert result.code_redeemed is None


def test_covered_by_tuition_for_tuition_paying_member(event, tuition_member):
    tier = PriceTier.objects.create(
        event=event,
        audience=Audience.MEMBER,
        base_amount=Decimal("100.00"),
        covered_by_tuition=True,
    )
    result = resolve_price(user=tuition_member, tier=tier)
    assert result.amount == Decimal("0.00")
    assert "tuition" in result.explanation.lower()


def test_covered_by_tuition_does_not_apply_to_non_tuition_member(event, regular_user):
    tier = PriceTier.objects.create(
        event=event,
        audience=Audience.MEMBER,
        base_amount=Decimal("100.00"),
        covered_by_tuition=True,
    )
    result = resolve_price(user=regular_user, tier=tier)
    assert result.amount == Decimal("100.00")


def test_covered_by_tuition_keys_on_the_events_academic_year(event, regular_user):
    """Coverage must key on the event's AY, not today's date (task #450
    phase A). `event` is dated Sept 2026 (AY2026-2027). A member who was
    PAID_IN_FULL for AY2025-2026 only should NOT get coverage on this
    tier — until they also have a covers-seminars enrollment for
    AY2026-2027, at which point they do."""
    from payments.models import TuitionEnrollment, TuitionPeriod

    # Note: the payments migration seeds a TuitionPeriod named "AY
    # 2025–2026" for "today" (name is unique) — use a distinct name here.
    old_period = TuitionPeriod.objects.create(
        name="AY 2025–2026 (pricing test)", slug="ay-2025-2026-test",
        start_date=date(2025, 9, 1), decision_due_date=date(2025, 10, 31),
        end_date=date(2026, 8, 31), tuition_amount=Decimal("800.00"),
    )
    TuitionEnrollment.objects.create(
        user=regular_user, tuition_period=old_period,
        status=TuitionEnrollment.Status.PAID_IN_FULL,
    )

    tier = PriceTier.objects.create(
        event=event,
        audience=Audience.MEMBER,
        base_amount=Decimal("100.00"),
        covered_by_tuition=True,
    )

    # Only the 2025-26 (old) enrollment exists: no coverage on the Sept-2026 event.
    result = resolve_price(user=regular_user, tier=tier)
    assert result.amount == Decimal("100.00")

    # Now the member also has a covers-seminars enrollment for 2026-27: covered.
    new_period = TuitionPeriod.objects.create(
        name="AY 2026–2027", slug="ay-2026-2027-test",
        start_date=date(2026, 9, 1), decision_due_date=date(2026, 10, 31),
        end_date=date(2027, 8, 31), tuition_amount=Decimal("800.00"),
    )
    TuitionEnrollment.objects.create(
        user=regular_user, tuition_period=new_period,
        status=TuitionEnrollment.Status.COMMITTED,
    )
    result = resolve_price(user=regular_user, tier=tier)
    assert result.amount == Decimal("0.00")


def test_sliding_scale_requires_amount(event, regular_user):
    tier = PriceTier.objects.create(
        event=event,
        audience=Audience.STUDENT,
        base_amount=Decimal("100.00"),
        sliding_scale=True,
        minimum_amount=Decimal("25.00"),
    )
    with pytest.raises(PricingError, match="requires a sliding_amount"):
        resolve_price(user=regular_user, tier=tier)


def test_sliding_scale_below_minimum_rejected(event, regular_user):
    tier = PriceTier.objects.create(
        event=event,
        audience=Audience.STUDENT,
        base_amount=Decimal("100.00"),
        sliding_scale=True,
        minimum_amount=Decimal("25.00"),
    )
    with pytest.raises(PricingError, match="below minimum"):
        resolve_price(user=regular_user, tier=tier, sliding_amount=Decimal("10.00"))


def test_sliding_scale_zero_minimum_accepts_zero(event, regular_user):
    """'None turned away for lack of funds' — minimum=0 must accept 0."""
    tier = PriceTier.objects.create(
        event=event,
        audience=Audience.ALL,
        base_amount=Decimal("100.00"),
        sliding_scale=True,
        minimum_amount=Decimal("0.00"),
    )
    result = resolve_price(user=regular_user, tier=tier, sliding_amount=Decimal("0.00"))
    assert result.amount == Decimal("0.00")


def test_sliding_scale_at_minimum_accepted(event, regular_user):
    tier = PriceTier.objects.create(
        event=event,
        audience=Audience.STUDENT,
        base_amount=Decimal("100.00"),
        sliding_scale=True,
        minimum_amount=Decimal("25.00"),
    )
    result = resolve_price(user=regular_user, tier=tier, sliding_amount=Decimal("25.00"))
    assert result.amount == Decimal("25.00")


def test_sliding_scale_above_base_allowed(event, regular_user):
    """A generous donor can pay more than base_amount on a sliding tier."""
    tier = PriceTier.objects.create(
        event=event,
        audience=Audience.ALL,
        base_amount=Decimal("100.00"),
        sliding_scale=True,
        minimum_amount=Decimal("0.00"),
    )
    result = resolve_price(user=regular_user, tier=tier, sliding_amount=Decimal("250.00"))
    assert result.amount == Decimal("250.00")


def test_negative_sliding_amount_rejected(event, regular_user):
    tier = PriceTier.objects.create(
        event=event,
        audience=Audience.ALL,
        base_amount=Decimal("100.00"),
        sliding_scale=True,
        minimum_amount=Decimal("0.00"),
    )
    with pytest.raises(PricingError, match="cannot be negative"):
        resolve_price(user=regular_user, tier=tier, sliding_amount=Decimal("-10.00"))


# --- Pricing-code overrides ---------------------------------------------


def test_percent_off_code(event, faculty, regular_user):
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("100.00")
    )
    code = PricingCode.objects.create(
        event=event,
        issued_by=faculty,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("25"),
    )
    result = resolve_price(user=regular_user, tier=tier, pricing_code=code)
    assert result.amount == Decimal("75.00")
    assert result.code_redeemed == code


def test_fixed_amount_code(event, faculty, regular_user):
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("100.00")
    )
    code = PricingCode.objects.create(
        event=event,
        issued_by=faculty,
        pricing_mode=PricingCode.Mode.FIXED_AMOUNT,
        amount_or_percent=Decimal("40.00"),
    )
    result = resolve_price(user=regular_user, tier=tier, pricing_code=code)
    assert result.amount == Decimal("40.00")
    assert "Fixed price" in result.explanation


def test_code_overrides_covered_by_tuition(event, faculty, tuition_member):
    """A code is an explicit faculty choice — it should win even over tuition exemption."""
    tier = PriceTier.objects.create(
        event=event,
        audience=Audience.MEMBER,
        base_amount=Decimal("100.00"),
        covered_by_tuition=True,
    )
    code = PricingCode.objects.create(
        event=event,
        issued_by=faculty,
        pricing_mode=PricingCode.Mode.FIXED_AMOUNT,
        amount_or_percent=Decimal("25.00"),
    )
    result = resolve_price(user=tuition_member, tier=tier, pricing_code=code)
    assert result.amount == Decimal("25.00")


def test_code_from_different_event_rejected(event, faculty, regular_user, db):
    other = Event.objects.create(
        title="Other", slug="other",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("100.00")
    )
    code = PricingCode.objects.create(
        event=other,
        issued_by=faculty,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("10"),
    )
    with pytest.raises(PricingError, match="does not apply"):
        resolve_price(user=regular_user, tier=tier, pricing_code=code)


def test_expired_code_rejected(event, faculty, regular_user):
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("100.00")
    )
    code = PricingCode.objects.create(
        event=event,
        issued_by=faculty,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("10"),
        valid_until=timezone.now() - timedelta(days=1),
    )
    with pytest.raises(PricingError, match="not redeemable"):
        resolve_price(user=regular_user, tier=tier, pricing_code=code)


def test_restricted_code_rejected_for_other_user(event, faculty, regular_user):
    sally = User.objects.create_user(email="sally@example.com")
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("100.00")
    )
    code = PricingCode.objects.create(
        event=event,
        issued_by=faculty,
        pricing_mode=PricingCode.Mode.FIXED_AMOUNT,
        amount_or_percent=Decimal("0"),
        restricted_to_user=sally,
    )
    with pytest.raises(PricingError, match="not redeemable"):
        resolve_price(user=regular_user, tier=tier, pricing_code=code)


def test_sliding_floor_code_requires_sliding_amount(event, faculty, regular_user):
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("100.00")
    )
    code = PricingCode.objects.create(
        event=event,
        issued_by=faculty,
        pricing_mode=PricingCode.Mode.SLIDING_FLOOR,
        amount_or_percent=Decimal("20.00"),
    )
    with pytest.raises(PricingError, match="sliding-scale"):
        resolve_price(user=regular_user, tier=tier, pricing_code=code)


def test_sliding_floor_code_below_floor_rejected(event, faculty, regular_user):
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("100.00")
    )
    code = PricingCode.objects.create(
        event=event,
        issued_by=faculty,
        pricing_mode=PricingCode.Mode.SLIDING_FLOOR,
        amount_or_percent=Decimal("20.00"),
    )
    with pytest.raises(PricingError, match="below floor"):
        resolve_price(
            user=regular_user, tier=tier, pricing_code=code,
            sliding_amount=Decimal("10.00"),
        )


def test_sliding_floor_code_at_floor_accepted(event, faculty, regular_user):
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("100.00")
    )
    code = PricingCode.objects.create(
        event=event,
        issued_by=faculty,
        pricing_mode=PricingCode.Mode.SLIDING_FLOOR,
        amount_or_percent=Decimal("20.00"),
    )
    result = resolve_price(
        user=regular_user, tier=tier, pricing_code=code,
        sliding_amount=Decimal("20.00"),
    )
    assert result.amount == Decimal("20.00")
    assert "Sliding scale via code" in result.explanation


def test_sliding_floor_code_above_floor_accepted(event, faculty, regular_user):
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("100.00")
    )
    code = PricingCode.objects.create(
        event=event,
        issued_by=faculty,
        pricing_mode=PricingCode.Mode.SLIDING_FLOOR,
        amount_or_percent=Decimal("20.00"),
    )
    result = resolve_price(
        user=regular_user, tier=tier, pricing_code=code,
        sliding_amount=Decimal("75.00"),
    )
    assert result.amount == Decimal("75.00")


def test_percent_off_floors_at_zero_not_negative(event, faculty, regular_user):
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("50.00")
    )
    code = PricingCode.objects.create(
        event=event,
        issued_by=faculty,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("100"),
    )
    result = resolve_price(user=regular_user, tier=tier, pricing_code=code)
    assert result.amount == Decimal("0.00")


def test_resolution_dataclass_default():
    """Sanity: PriceResolution defaults code_redeemed to None."""
    r = PriceResolution(amount=Decimal("10.00"), explanation="test")
    assert r.code_redeemed is None
