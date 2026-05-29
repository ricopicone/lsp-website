"""Tests for the dues + donations flows (REG-12, REG-13) and thanks page."""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.core import mail
from django.urls import reverse

from accounts.models import User
from payments.models import Payment


@pytest.fixture(autouse=True)
def stub_stripe(monkeypatch):
    """Stub all stripe session creators so tests don't hit the API."""
    stub_dues = MagicMock(return_value=MagicMock(id="cs_dues_test", url="https://stripe.test/dues"))
    stub_don = MagicMock(return_value=MagicMock(id="cs_don_test", url="https://stripe.test/donate"))
    monkeypatch.setattr("payments.views.create_dues_session", stub_dues)
    monkeypatch.setattr("payments.views.create_donation_session", stub_don)
    return {"dues": stub_dues, "donate": stub_don}


@pytest.fixture
def user(db):
    """A dues-tier-mapped user (Candidate). Tier amount comes from the seed
    DuesPeriod or the DUES_CANDIDATE_AMOUNT setting if no period covers today."""
    from accounts.models import Profile
    u = User.objects.create_user(email="r@example.com", password="testpass-XYZ")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.save()
    return u


# ---- Dues -------------------------------------------------------------


def test_dues_anonymous_redirects_to_login(client):
    response = client.get(reverse("dues"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_dues_get_shows_amount(client, user):
    client.force_login(user)
    response = client.get(reverse("dues"))
    assert response.status_code == 200
    # CANDIDATE → seed period's $100.00 candidate tier.
    assert b"$100.00" in response.content
    assert b"r@example.com" in response.content  # receipt destination


def test_dues_post_creates_payment_and_redirects_to_stripe(client, user, stub_stripe):
    client.force_login(user)
    response = client.post(reverse("dues"))
    assert response.status_code == 302
    assert response.url == "https://stripe.test/dues"
    payment = Payment.objects.get(payment_type=Payment.Type.DUES, user=user)
    assert payment.amount == Decimal("100.00")
    assert payment.status == Payment.Status.PENDING
    stub_stripe["dues"].assert_called_once_with(payment)


# ---- Donations --------------------------------------------------------


@pytest.mark.django_db
def test_donate_get_renders_anon_form(client):
    response = client.get(reverse("donate"))
    assert response.status_code == 200
    assert b"Email" in response.content


def test_donate_get_renders_for_logged_in(client, user):
    client.force_login(user)
    response = client.get(reverse("donate"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_donate_anon_requires_email(client):
    response = client.post(reverse("donate"), {"amount": "25.00"})
    assert response.status_code == 200
    assert b"Email is required" in response.content
    assert Payment.objects.count() == 0


@pytest.mark.django_db
def test_donate_anon_post_creates_payment(client, stub_stripe):
    response = client.post(
        reverse("donate"),
        {
            "amount": "50.00",
            "email": "anon@example.com",
            "name": "Anonymous Donor",
            "dedication": "For the cartels",
        },
    )
    assert response.status_code == 302
    assert response.url == "https://stripe.test/donate"
    payment = Payment.objects.get(payment_type=Payment.Type.DONATION)
    assert payment.amount == Decimal("50.00")
    assert payment.user is None
    assert payment.email == "anon@example.com"
    assert payment.notes == "For the cartels"
    stub_stripe["donate"].assert_called_once()
    # The session helper was given the right email for anonymous receipt.
    assert stub_stripe["donate"].call_args.kwargs["customer_email"] == "anon@example.com"


def test_donate_auth_post_creates_payment_with_user(client, user, stub_stripe):
    client.force_login(user)
    response = client.post(reverse("donate"), {"amount": "75.00"})
    assert response.status_code == 302
    payment = Payment.objects.get(payment_type=Payment.Type.DONATION)
    assert payment.user == user
    assert payment.email == ""  # falls through to user.email
    assert stub_stripe["donate"].call_args.kwargs["customer_email"] == "r@example.com"


@pytest.mark.django_db
def test_donate_zero_amount_rejected(client):
    response = client.post(
        reverse("donate"),
        {"amount": "0.00", "email": "anon@example.com"},
    )
    assert response.status_code == 200
    assert Payment.objects.count() == 0


# ---- Thanks page ------------------------------------------------------


@pytest.mark.django_db
def test_thanks_page_dues(client, user):
    payment = Payment.objects.create(
        payment_type=Payment.Type.DUES,
        user=user, amount=Decimal("100.00"),
        status=Payment.Status.SUCCEEDED,
    )
    response = client.get(reverse("payments:thanks", args=[payment.id]))
    assert response.status_code == 200
    assert b"membership dues" in response.content.lower()
    assert b"$100.00" in response.content


@pytest.mark.django_db
def test_thanks_page_donation_anon_accessible(client):
    payment = Payment.objects.create(
        payment_type=Payment.Type.DONATION,
        user=None, email="anon@example.com",
        amount=Decimal("25.00"),
        status=Payment.Status.SUCCEEDED,
    )
    response = client.get(reverse("payments:thanks", args=[payment.id]))
    assert response.status_code == 200
    assert b"donation" in response.content.lower()


@pytest.mark.django_db
def test_thanks_page_404_for_registration_payment(client, user):
    from datetime import date

    from events.models import Audience, Event, PriceTier
    from registrations.models import Registration
    event = Event.objects.create(
        title="E", slug="e",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("100.00")
    )
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
    )
    payment = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=reg, user=user, amount=Decimal("100.00"),
    )
    response = client.get(reverse("payments:thanks", args=[payment.id]))
    assert response.status_code == 404


# ---- Webhook handles non-registration payments ------------------------


@pytest.mark.django_db
def test_webhook_for_dues_marks_paid_creates_receipt_sends_email(client, user):
    payment = Payment.objects.create(
        payment_type=Payment.Type.DUES,
        user=user, amount=Decimal("100.00"),
        stripe_checkout_session_id="cs_test_dues_hook",
    )
    payload = {
        "id": "evt_dues_1",
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_test_dues_hook", "payment_intent": "pi_dues_xyz"}},
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
    # Only one email — the receipt (which doubles as confirmation for dues).
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert "Receipt LSP-" in msg.subject
    assert "annual membership dues" in msg.body.lower()
    assert msg.to == [user.email]


@pytest.mark.django_db
def test_webhook_for_anon_donation_emails_payment_email(client):
    payment = Payment.objects.create(
        payment_type=Payment.Type.DONATION,
        user=None, email="anon@example.com",
        amount=Decimal("50.00"),
        stripe_checkout_session_id="cs_test_donation_hook",
    )
    payload = {
        "id": "evt_donation_1",
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_test_donation_hook", "payment_intent": "pi_d"}},
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
    assert mail.outbox[0].to == ["anon@example.com"]
    assert "donation" in mail.outbox[0].body.lower()


# ---- recipient_email property -----------------------------------------


@pytest.mark.django_db
def test_recipient_email_prefers_user(user):
    payment = Payment.objects.create(
        payment_type=Payment.Type.DONATION,
        user=user, email="ignored@example.com",
        amount=Decimal("10.00"),
    )
    assert payment.recipient_email == "r@example.com"


@pytest.mark.django_db
def test_recipient_email_falls_back_to_email_field():
    payment = Payment.objects.create(
        payment_type=Payment.Type.DONATION,
        user=None, email="anon@example.com",
        amount=Decimal("10.00"),
    )
    assert payment.recipient_email == "anon@example.com"


@pytest.mark.django_db
def test_recipient_email_none_when_nothing_set():
    payment = Payment.objects.create(
        payment_type=Payment.Type.DONATION,
        user=None, email="",
        amount=Decimal("10.00"),
    )
    assert payment.recipient_email is None
