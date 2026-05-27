"""Tests for the payments data model."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User
from events.models import Audience, Event, PriceTier
from payments.models import Payment, Receipt
from registrations.models import Registration


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="E", slug="e",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )


@pytest.fixture
def tier(event):
    return PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("100.00")
    )


@pytest.fixture
def registration(db, event, tier):
    user = User.objects.create_user(email="r@example.com")
    return Registration.objects.create(
        user=user, event=event, price_tier=tier, quoted_amount=Decimal("100.00")
    )


# --- Payment ------------------------------------------------------------


@pytest.mark.django_db
def test_payment_create_minimal(registration):
    p = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=registration,
        user=registration.user,
        amount=Decimal("100.00"),
    )
    assert p.status == Payment.Status.PENDING
    assert p.method == Payment.Method.STRIPE
    assert p.paid_at is None
    assert "Pending" in str(p)


@pytest.mark.django_db
def test_payment_mark_succeeded_sets_paid_at(registration):
    p = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=registration,
        amount=Decimal("100.00"),
    )
    p.mark_succeeded()
    p.refresh_from_db()
    assert p.status == Payment.Status.SUCCEEDED
    assert p.paid_at is not None


@pytest.mark.django_db
def test_payment_mark_succeeded_is_idempotent(registration):
    p = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=registration,
        amount=Decimal("100.00"),
    )
    p.mark_succeeded()
    first_paid_at = p.paid_at
    p.mark_succeeded()
    p.refresh_from_db()
    assert p.paid_at == first_paid_at


@pytest.mark.django_db
def test_dues_payment_has_no_registration():
    user = User.objects.create_user(email="dues@example.com")
    p = Payment.objects.create(
        payment_type=Payment.Type.DUES,
        user=user,
        amount=Decimal("75.00"),
    )
    assert p.registration is None
    assert p.payment_type == Payment.Type.DUES
    assert "dues" in str(p).lower()


@pytest.mark.django_db
def test_stripe_session_id_unique_when_set(registration):
    """Two Payments can share blank stripe_checkout_session_id but not a real one."""
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=registration,
        amount=Decimal("100.00"),
    )
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=registration,
        amount=Decimal("100.00"),
    )

    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=registration,
        amount=Decimal("100.00"),
        stripe_checkout_session_id="cs_test_xyz",
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Payment.objects.create(
            payment_type=Payment.Type.REGISTRATION,
            registration=registration,
            amount=Decimal("100.00"),
            stripe_checkout_session_id="cs_test_xyz",
        )


# --- Receipt ------------------------------------------------------------


@pytest.mark.django_db
def test_receipt_number_format_and_sequential(registration):
    p1 = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=registration,
        amount=Decimal("100.00"),
    )
    p2 = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=registration,
        amount=Decimal("100.00"),
    )
    r1 = Receipt.create_for_payment(p1)
    r2 = Receipt.create_for_payment(p2)
    year = timezone.now().year
    assert r1.receipt_number == f"LSP-{year}-0001"
    assert r2.receipt_number == f"LSP-{year}-0002"


@pytest.mark.django_db
def test_receipt_resets_per_year(registration):
    """Receipt numbering is per year; a new year starts at 0001 again."""
    p1 = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=registration,
        amount=Decimal("100.00"),
    )
    Receipt.create_for_payment(p1)

    p2 = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=registration,
        amount=Decimal("100.00"),
    )
    future = timezone.now().replace(year=timezone.now().year + 1)
    with patch("payments.models.timezone") as mock_tz:
        mock_tz.now.return_value = future
        r2 = Receipt.create_for_payment(p2)
    assert r2.receipt_number == f"LSP-{future.year}-0001"
