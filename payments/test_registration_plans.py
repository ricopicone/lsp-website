"""Registration payment plans (task #501)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import Profile, User
from events.models import Audience, Event, PriceTier, PricingCode
from events.pricing import resolve_price

pytestmark = pytest.mark.django_db


def _user(email="member@example.com"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    return u


def _event(title="Seminar", **kwargs):
    today = timezone.localdate()
    return Event.objects.create(
        title=title,
        slug=title.lower().replace(" ", "-"),
        event_type=Event.Type.SEMINAR,
        start_date=today + timedelta(days=7),
        end_date=today + timedelta(days=90),
        published=True,
        status=Event.Status.OPEN,
        **kwargs,
    )


def _tier(event, amount="500.00", **kwargs):
    return PriceTier.objects.create(
        event=event, audience=Audience.ALL,
        base_amount=Decimal(amount), **kwargs,
    )


def _code(event, issuer, **kwargs):
    kwargs.setdefault("pricing_mode", PricingCode.Mode.FULL_PRICE)
    kwargs.setdefault("amount_or_percent", Decimal("0"))
    return PricingCode.objects.create(event=event, issued_by=issuer, **kwargs)


# ---- Task 1: the code carries a count and a full-price mode -------------


def test_installments_defaults_to_one():
    issuer = _user("faculty@example.com")
    event = _event()
    code = _code(event, issuer)
    assert code.installments == 1


def test_plain_code_resolution_is_unchanged():
    """installments=1 must resolve byte-identically to today."""
    issuer = _user("faculty@example.com")
    member = _user()
    event = _event()
    tier = _tier(event)
    code = _code(
        event, issuer,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("20"),
    )
    r = resolve_price(user=member, tier=tier, pricing_code=code)
    assert r.amount == Decimal("400.00")
    assert r.installments == 1


def test_full_price_mode_returns_the_tier_base():
    issuer = _user("faculty@example.com")
    member = _user()
    event = _event()
    tier = _tier(event)
    code = _code(event, issuer, installments=3)
    r = resolve_price(user=member, tier=tier, pricing_code=code)
    assert r.amount == Decimal("500.00")
    assert r.installments == 3
    assert code.code in r.explanation


def test_a_discount_and_a_plan_are_independent_axes():
    issuer = _user("faculty@example.com")
    member = _user()
    event = _event()
    tier = _tier(event)
    code = _code(
        event, issuer,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("20"),
        installments=3,
    )
    r = resolve_price(user=member, tier=tier, pricing_code=code)
    assert r.amount == Decimal("400.00")   # the plan did not change the total
    assert r.installments == 3


def test_installment_count_is_bounded():
    from django.core.exceptions import ValidationError
    issuer = _user("faculty@example.com")
    event = _event()
    code = PricingCode(
        event=event, issued_by=issuer,
        pricing_mode=PricingCode.Mode.FULL_PRICE,
        amount_or_percent=Decimal("0"),
        installments=0,
    )
    with pytest.raises(ValidationError):
        code.clean()
    code.installments = 13
    with pytest.raises(ValidationError):
        code.clean()
    code.installments = 3
    code.clean()   # no raise
