"""Tests for the Stripe webhook handler (idempotent, signature-verified)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.urls import reverse

from accounts.models import User
from events.models import Audience, Event, PriceTier
from payments.models import Payment, Receipt
from registrations.models import Registration


@pytest.fixture
def payment(db):
    user = User.objects.create_user(email="r@example.com")
    event = Event.objects.create(
        title="X", slug="x",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("100.00")
    )
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier, quoted_amount=Decimal("100.00")
    )
    return Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=reg,
        user=user,
        amount=Decimal("100.00"),
        stripe_checkout_session_id="cs_test_abc",
    )


def _event_payload(session_id: str, intent_id: str = "pi_test_xyz") -> dict:
    return {
        "id": "evt_test_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "payment_intent": intent_id,
                "amount_total": 10000,
                "currency": "usd",
            },
        },
    }


def _post_event(client, payload: dict):
    """POST to the webhook view, bypassing signature verification via patch."""
    body = json.dumps(payload).encode("utf-8")
    with patch(
        "payments.views.stripe.Webhook.construct_event",
        return_value=payload,
    ):
        return client.post(
            reverse("payments:stripe_webhook"),
            data=body,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=test",
        )


@override_settings(STRIPE_WEBHOOK_SECRET="whsec_test")
def test_invalid_signature_returns_400(client, payment):
    """Verify the verification step is wired — bad signature → 400."""
    body = json.dumps(_event_payload("cs_test_abc")).encode("utf-8")
    response = client.post(
        reverse("payments:stripe_webhook"),
        data=body,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=bogus",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_checkout_completed_marks_paid_and_creates_receipt(client, payment):
    response = _post_event(client, _event_payload("cs_test_abc"))
    assert response.status_code == 200

    payment.refresh_from_db()
    assert payment.status == Payment.Status.SUCCEEDED
    assert payment.paid_at is not None
    assert payment.stripe_payment_intent_id == "pi_test_xyz"

    payment.registration.refresh_from_db()
    assert payment.registration.status == Registration.Status.PAID

    assert hasattr(payment, "receipt")
    assert payment.receipt.receipt_number.startswith("LSP-")


@pytest.mark.django_db
def test_replayed_event_does_nothing(client, payment):
    _post_event(client, _event_payload("cs_test_abc"))
    payment.refresh_from_db()
    first_paid_at = payment.paid_at
    first_receipt_id = payment.receipt.id

    # Replay the same event.
    response = _post_event(client, _event_payload("cs_test_abc"))
    assert response.status_code == 200

    payment.refresh_from_db()
    payment.receipt.refresh_from_db()
    assert payment.paid_at == first_paid_at
    assert payment.receipt.id == first_receipt_id
    # Still exactly one receipt total for this payment.
    assert Receipt.objects.filter(payment=payment).count() == 1


@pytest.mark.django_db
def test_unknown_session_id_is_a_noop(client, payment):
    response = _post_event(client, _event_payload("cs_unknown_123"))
    # We return 200 (don't make Stripe retry) and don't touch the existing Payment.
    assert response.status_code == 200
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING


@pytest.mark.django_db
def test_other_event_type_is_ignored(client, payment):
    payload = _event_payload("cs_test_abc")
    payload["type"] = "customer.created"
    response = _post_event(client, payload)
    assert response.status_code == 200
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING


@pytest.mark.django_db
def test_get_method_rejected(client):
    response = client.get(reverse("payments:stripe_webhook"))
    assert response.status_code == 405


# ---- livemode guard (keep test data out of accounting) --------------------

def _event(session_id, *, livemode, intent="pi_x"):
    return {
        "id": "evt_lm", "type": "checkout.session.completed", "livemode": livemode,
        "data": {"object": {
            "id": session_id, "payment_intent": intent,
            "amount_total": 10000, "currency": "usd", "livemode": livemode,
        }},
    }


@pytest.mark.django_db
@override_settings(STRIPE_LIVE_ONLY=True)
def test_test_mode_event_ignored_when_live_only(client, payment):
    resp = _post_event(client, _event(payment.stripe_checkout_session_id, livemode=False))
    assert resp.status_code == 200
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING  # never completed


@pytest.mark.django_db
@override_settings(STRIPE_LIVE_ONLY=False)
def test_test_mode_event_processed_in_dev_records_livemode(client, payment):
    resp = _post_event(client, _event(payment.stripe_checkout_session_id, livemode=False))
    assert resp.status_code == 200
    payment.refresh_from_db()
    assert payment.status == Payment.Status.SUCCEEDED
    assert payment.livemode is False


@pytest.mark.django_db
@override_settings(STRIPE_LIVE_ONLY=True)
def test_live_event_completes_and_records_livemode_true(client, payment):
    resp = _post_event(client, _event(payment.stripe_checkout_session_id, livemode=True))
    assert resp.status_code == 200
    payment.refresh_from_db()
    assert payment.status == Payment.Status.SUCCEEDED
    assert payment.livemode is True
