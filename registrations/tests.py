"""Tests for the Registration model."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from accounts.models import User
from events.models import Audience, Event, PriceTier
from registrations.models import Registration


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="X", slug="x",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )


@pytest.fixture
def tier(event):
    return PriceTier.objects.create(
        event=event, audience=Audience.STUDENT, base_amount=Decimal("100.00")
    )


@pytest.fixture
def user(db):
    return User.objects.create_user(email="r@example.com")


@pytest.mark.django_db
def test_registration_create_minimal(event, tier, user):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier, quoted_amount=Decimal("100.00")
    )
    assert reg.status == Registration.Status.AWAITING_PAYMENT
    assert reg.pricing_code is None
    assert "Awaiting payment" in str(reg)


@pytest.mark.django_db
def test_registration_default_explanation_blank(event, tier, user):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier, quoted_amount=Decimal("100.00")
    )
    assert reg.quoted_explanation == ""


@pytest.mark.django_db
def test_registration_status_choices(event, tier):
    """Verify each status round-trips. Each gets its own user so the
    one-active-per-(user, event) constraint doesn't reject the loop."""
    for i, status in enumerate([
        Registration.Status.AWAITING_PAYMENT,
        Registration.Status.PAID,
        Registration.Status.COMPED,
        Registration.Status.CANCELLED,
        Registration.Status.REFUNDED,
    ]):
        user = User.objects.create_user(email=f"u{i}@example.com")
        reg = Registration.objects.create(
            user=user, event=event, price_tier=tier,
            quoted_amount=Decimal("0"), status=status,
        )
        reg.refresh_from_db()
        assert reg.status == status


@pytest.mark.django_db
def test_unique_active_registration_constraint_rejects_duplicate(event, tier, user):
    from django.db import IntegrityError, transaction
    Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("0"), status=Registration.Status.AWAITING_PAYMENT,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Registration.objects.create(
            user=user, event=event, price_tier=tier,
            quoted_amount=Decimal("0"), status=Registration.Status.PAID,
        )


@pytest.mark.django_db
def test_unique_active_registration_constraint_allows_cancelled_then_new(
    event, tier, user,
):
    cancelled = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("0"), status=Registration.Status.CANCELLED,
    )
    fresh = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("0"), status=Registration.Status.AWAITING_PAYMENT,
    )
    assert cancelled.pk != fresh.pk


@pytest.mark.django_db
def test_unique_active_registration_constraint_allows_multiple_cancelled(
    event, tier, user,
):
    """Historical cancelled rows shouldn't conflict with each other."""
    Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("0"), status=Registration.Status.CANCELLED,
    )
    Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("0"), status=Registration.Status.REFUNDED,
    )
    assert Registration.objects.filter(user=user, event=event).count() == 2
