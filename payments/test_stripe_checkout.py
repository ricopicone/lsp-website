"""Tests for payments.stripe_checkout — Stripe Session creator."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from accounts.models import User
from events.models import Audience, Event, PriceTier
from payments.models import Payment
from payments.stripe_checkout import create_checkout_session
from registrations.models import Registration


@pytest.fixture
def registration(db):
    user = User.objects.create_user(email="r@example.com")
    event = Event.objects.create(
        title="Lacan Seminar", slug="lacan",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    tier = PriceTier.objects.create(
        event=event, audience=Audience.STUDENT, base_amount=Decimal("100.00"),
    )
    return Registration.objects.create(
        user=user, event=event, price_tier=tier, quoted_amount=Decimal("75.00"),
    )


@pytest.mark.django_db
def test_create_checkout_session_makes_payment_and_stores_session_id(registration):
    fake_session = MagicMock(id="cs_test_abc123", url="https://stripe.test/cs_test_abc123")
    with patch("payments.stripe_checkout.stripe.checkout.Session.create",
               return_value=fake_session) as create:
        payment, session = create_checkout_session(registration)

    assert payment.status == Payment.Status.PENDING
    assert payment.method == Payment.Method.STRIPE
    assert payment.amount == Decimal("75.00")
    assert payment.registration == registration
    assert payment.user == registration.user
    assert payment.stripe_checkout_session_id == "cs_test_abc123"
    assert session is fake_session

    # Stripe was called with expected line items + amount.
    create.assert_called_once()
    kwargs = create.call_args.kwargs
    assert kwargs["customer_email"] == registration.user.email
    assert kwargs["client_reference_id"] == str(payment.id)
    assert kwargs["line_items"][0]["price_data"]["unit_amount"] == 7500
    assert kwargs["line_items"][0]["price_data"]["currency"] == "usd"
    assert kwargs["metadata"]["payment_id"] == str(payment.id)
    assert kwargs["metadata"]["payment_type"] == "registration"
    assert "stripe=success" in kwargs["success_url"]
    assert "stripe=cancelled" in kwargs["cancel_url"]


@pytest.mark.django_db
def test_create_checkout_session_refuses_zero_amount(registration):
    registration.quoted_amount = Decimal("0.00")
    registration.save()
    with pytest.raises(ValueError, match="\\$0 registration"):
        create_checkout_session(registration)
    # Sanity: no Payment row created.
    assert Payment.objects.count() == 0


@pytest.mark.django_db
def test_checkout_offers_card_only_never_buy_now_pay_later(registration):
    """Regression pin (task #494): a Board member asked whether the school
    uses Klarna. It doesn't — and this explicit ``payment_method_types`` is
    the only reason. Passing it opts the Session out of Stripe's dynamic
    payment methods, the Dashboard-managed set where Klarna / Affirm /
    Afterpay live and which Stripe enables by default. Drop the argument and
    BNPL appears at checkout with no other code change.
    """
    fake_session = MagicMock(id="cs_test_pm", url="https://stripe.test/cs_test_pm")
    with patch("payments.stripe_checkout.stripe.checkout.Session.create",
               return_value=fake_session) as create:
        create_checkout_session(registration)

    assert create.call_args.kwargs["payment_method_types"] == ["card"]
