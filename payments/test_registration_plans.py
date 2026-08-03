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


# ---- Task 2: the installment model --------------------------------------


def _registration(user, event, tier, amount="500.00", **kwargs):
    from registrations.models import Registration
    kwargs.setdefault("status", Registration.Status.AWAITING_PAYMENT)
    return Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal(amount), **kwargs,
    )


def test_installment_rows_hang_off_the_registration():
    from payments.models import RegistrationInstallment
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier)
    inst = RegistrationInstallment.objects.create(
        registration=reg, sequence=1,
        due_date=timezone.localdate(), amount=Decimal("166.66"),
    )
    assert list(reg.installments.all()) == [inst]
    assert inst.paid is False

    inst.mark_paid()
    inst.refresh_from_db()
    assert inst.paid is True
    assert inst.paid_at is not None

    before = inst.paid_at
    inst.mark_paid()          # idempotent
    inst.refresh_from_db()
    assert inst.paid_at == before


def test_installment_sequence_is_unique_per_registration():
    from django.db import IntegrityError
    from payments.models import RegistrationInstallment
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier)
    RegistrationInstallment.objects.create(
        registration=reg, sequence=1,
        due_date=timezone.localdate(), amount=Decimal("250.00"),
    )
    with pytest.raises(IntegrityError):
        RegistrationInstallment.objects.create(
            registration=reg, sequence=1,
            due_date=timezone.localdate(), amount=Decimal("250.00"),
        )


def test_a_payment_can_point_at_an_installment():
    from payments.models import Payment, RegistrationInstallment
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier)
    inst = RegistrationInstallment.objects.create(
        registration=reg, sequence=1,
        due_date=timezone.localdate(), amount=Decimal("166.66"),
    )
    p = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, registration=reg,
        user=member, amount=Decimal("166.66"),
        registration_installment=inst,
    )
    assert list(inst.payments.all()) == [p]
