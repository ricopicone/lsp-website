"""Tests for the transactional emails (REG-7, REG-8, REG-9)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core import mail
from django.urls import reverse

from accounts.models import User
from events.models import Audience, Event, PriceTier
from payments.emails import send_registration_confirmation
from payments.models import Payment, Receipt
from registrations.models import Registration


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Lacan Seminar",
        slug="lacan",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 15),
        access_info="Zoom: https://example.zoom.us/j/123 — password: secret",
        published=True,
        status=Event.Status.OPEN,
    )


@pytest.fixture
def tier(event):
    return PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("100.00")
    )


@pytest.fixture
def registration(db, event, tier):
    user = User.objects.create_user(email="r@example.com", first_name="Reggie")
    return Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.PAID,
    )


@pytest.mark.django_db
def test_confirmation_email_includes_access_info_when_paid(registration):
    send_registration_confirmation(registration)
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["r@example.com"]
    assert "Lacan Seminar" in msg.subject
    assert "Zoom" in msg.body
    assert "secret" in msg.body  # access_info content released


@pytest.mark.django_db
def test_confirmation_email_omits_access_info_when_awaiting_payment(registration):
    registration.status = Registration.Status.AWAITING_PAYMENT
    registration.save()
    send_registration_confirmation(registration)
    msg = mail.outbox[0]
    # Access info is gated on PAID status — should not leak to awaiting-payment regs.
    assert "Zoom" not in msg.body
    assert "secret" not in msg.body


@pytest.mark.django_db
def test_webhook_sends_both_emails_and_stamps_receipt(client, registration, tier):
    """End-to-end: webhook → payment paid → receipt created → both emails sent."""
    payment = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=registration,
        user=registration.user,
        amount=Decimal("100.00"),
        stripe_checkout_session_id="cs_test_emails",
    )
    # Registration starts as PAID in fixture; reset for honest end-to-end.
    registration.status = Registration.Status.AWAITING_PAYMENT
    registration.save()

    payload = {
        "id": "evt_emails_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_emails",
                "payment_intent": "pi_test_emails",
            },
        },
    }
    with patch(
        "payments.views.stripe.Webhook.construct_event",
        return_value=payload,
    ):
        response = client.post(
            reverse("payments:stripe_webhook"),
            data=json.dumps(payload).encode("utf-8"),
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=test",
        )
    assert response.status_code == 200

    payment.refresh_from_db()
    assert payment.status == Payment.Status.SUCCEEDED
    assert hasattr(payment, "receipt")
    payment.receipt.refresh_from_db()
    assert payment.receipt.emailed_at is not None

    # Two emails: confirmation (with access_info now that it's PAID) and receipt.
    subjects = [m.subject for m in mail.outbox]
    assert any("Registration confirmed" in s for s in subjects)
    assert any("Receipt LSP-" in s for s in subjects)
    # The receipt is for the right amount.
    receipt_body = next(m.body for m in mail.outbox if "Receipt LSP-" in m.subject)
    assert "$100.00" in receipt_body
    assert payment.receipt.receipt_number in receipt_body


@pytest.mark.django_db
def test_replayed_webhook_does_not_re_send_emails(client, registration):
    payment = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=registration,
        user=registration.user,
        amount=Decimal("100.00"),
        stripe_checkout_session_id="cs_test_replay",
    )
    registration.status = Registration.Status.AWAITING_PAYMENT
    registration.save()

    payload = {
        "id": "evt_replay_1",
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_test_replay"}},
    }
    with patch(
        "payments.views.stripe.Webhook.construct_event",
        return_value=payload,
    ):
        client.post(
            reverse("payments:stripe_webhook"),
            data=json.dumps(payload).encode("utf-8"),
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=test",
        )
        first_count = len(mail.outbox)

        # Replay.
        client.post(
            reverse("payments:stripe_webhook"),
            data=json.dumps(payload).encode("utf-8"),
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=test",
        )
    assert len(mail.outbox) == first_count  # no new emails on replay
    assert Receipt.objects.filter(payment=payment).count() == 1


@pytest.mark.django_db
def test_zero_dollar_registration_sends_confirmation_directly(client, event, tier):
    """The $0 short-circuit path also emails the confirmation (with access_info)."""
    tier.sliding_scale = True
    tier.minimum_amount = Decimal("0.00")
    tier.save()

    user = User.objects.create_user(email="zero@example.com", password="testpass-XYZ")
    client.force_login(user)
    client.post(
        reverse("registrations:register", args=[event.slug]),
        {"price_tier": tier.id, "sliding_amount": "0"},
    )
    assert len(mail.outbox) == 1
    assert "Registration confirmed" in mail.outbox[0].subject
    assert "Zoom" in mail.outbox[0].body
