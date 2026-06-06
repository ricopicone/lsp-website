"""Tests for the self-cancel + refund flow (REG-16)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.core import mail
from django.urls import reverse

from accounts.models import User
from events.models import Audience, Event, PriceTier, PricingCode
from payments.models import Payment, Receipt
from payments.refund import RefundError
from registrations.models import Registration


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Cancellable",
        slug="cancellable",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 15),
        published=True,
        status=Event.Status.OPEN,
    )


@pytest.fixture
def tier(event):
    return PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("100.00")
    )


@pytest.fixture
def user(db):
    return User.objects.create_user(email="r@example.com", password="testpass-XYZ")


@pytest.fixture
def faculty(db):
    u = User.objects.create_user(email="fac@example.com")
    u.profile.is_faculty = True
    u.profile.save()
    return u


# ---- Registration.cancel() model behavior ------------------------------


@pytest.mark.django_db
def test_cancel_awaiting_payment_marks_cancelled(event, tier, user):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.AWAITING_PAYMENT,
    )
    refund = reg.cancel()
    assert refund is None
    reg.refresh_from_db()
    assert reg.status == Registration.Status.CANCELLED


@pytest.mark.django_db
def test_cancel_idempotent(event, tier, user):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.CANCELLED,
    )
    assert reg.cancel() is None  # no-op
    reg.refresh_from_db()
    assert reg.status == Registration.Status.CANCELLED


@pytest.mark.django_db
def test_cancel_paid_calls_refund_and_marks_refunded(event, tier, user):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.PAID,
    )
    payment = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=reg, user=user,
        amount=Decimal("100.00"),
        status=Payment.Status.SUCCEEDED,
        method=Payment.Method.STRIPE,
        stripe_payment_intent_id="pi_test_xyz",
    )
    fake_refund = MagicMock(id="re_test_abc", amount=10000)
    fake_refund.__getitem__ = lambda self, k: {"id": "re_test_abc", "amount": 10000}[k]
    with patch(
        "payments.refund.stripe.Refund.create", return_value=fake_refund
    ) as stripe_call:
        refund = reg.cancel()
    assert refund is fake_refund
    stripe_call.assert_called_once_with(payment_intent="pi_test_xyz")
    reg.refresh_from_db()
    payment.refresh_from_db()
    assert reg.status == Registration.Status.REFUNDED
    assert payment.status == Payment.Status.REFUNDED


@pytest.mark.django_db
def test_cancel_paid_offline_payment_raises(event, tier, user):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.PAID,
    )
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=reg, user=user,
        amount=Decimal("100.00"),
        status=Payment.Status.SUCCEEDED,
        method=Payment.Method.OFFLINE,
    )
    # No Stripe payment → cancel() can't find one with method=STRIPE,
    # raises RuntimeError so the caller can route to staff.
    with pytest.raises(RuntimeError):
        reg.cancel()


@pytest.mark.django_db
def test_cancel_restores_pricing_code_uses(event, tier, user, faculty):
    code = PricingCode.objects.create(
        event=event, issued_by=faculty,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("25"),
        max_uses=2,
    )
    code.uses_remaining = 1  # one use already consumed
    code.save()
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        pricing_code=code,
        quoted_amount=Decimal("75.00"),
        status=Registration.Status.AWAITING_PAYMENT,
    )
    reg.cancel()
    code.refresh_from_db()
    assert code.uses_remaining == 2  # restored


@pytest.mark.django_db
def test_cancel_no_code_leaves_other_codes_untouched(event, tier, user):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.AWAITING_PAYMENT,
    )
    reg.cancel()
    assert PricingCode.objects.count() == 0  # no crash


# ---- cancel_registration view -----------------------------------------


def test_cancel_view_owner_only(client, event, tier, user):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
    )
    other = User.objects.create_user(email="other@example.com", password="testpass-XYZ")
    client.force_login(other)
    response = client.post(reverse("registrations:cancel", args=[reg.id]))
    assert response.status_code == 404
    reg.refresh_from_db()
    assert reg.status == Registration.Status.AWAITING_PAYMENT


def test_cancel_view_anonymous_redirects(client, event, tier, user):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
    )
    response = client.post(reverse("registrations:cancel", args=[reg.id]))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_cancel_view_get_rejected(client, event, tier, user):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
    )
    client.force_login(user)
    response = client.get(reverse("registrations:cancel", args=[reg.id]))
    assert response.status_code == 405


def test_cancel_view_awaiting_payment_succeeds(
    client, event, tier, user, django_capture_on_commit_callbacks
):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.AWAITING_PAYMENT,
    )
    client.force_login(user)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(reverse("registrations:cancel", args=[reg.id]))
    assert response.status_code == 302
    assert response.url.endswith(
        reverse("registrations:confirm", args=[reg.id]) + "?cancelled=1"
    )
    reg.refresh_from_db()
    assert reg.status == Registration.Status.CANCELLED
    # Cancellation email sent
    assert any("Registration cancelled" in m.subject for m in mail.outbox)


def test_cancel_view_already_cancelled_is_idempotent(client, event, tier, user):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.CANCELLED,
    )
    client.force_login(user)
    response = client.post(reverse("registrations:cancel", args=[reg.id]))
    assert response.status_code == 302
    # No second email
    assert len(mail.outbox) == 0


def test_cancel_view_paid_invokes_stripe_refund(
    client, event, tier, user, django_capture_on_commit_callbacks
):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.PAID,
    )
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=reg, user=user,
        amount=Decimal("100.00"),
        status=Payment.Status.SUCCEEDED,
        method=Payment.Method.STRIPE,
        stripe_payment_intent_id="pi_test_xyz",
    )
    fake_refund = MagicMock()
    fake_refund.__getitem__ = lambda self, k: {"id": "re_x", "amount": 10000}[k]
    fake_refund.__contains__ = lambda self, k: k in ("id", "amount")
    client.force_login(user)
    with patch("payments.refund.stripe.Refund.create", return_value=fake_refund) as call, \
            django_capture_on_commit_callbacks(execute=True):
        response = client.post(reverse("registrations:cancel", args=[reg.id]))
    assert response.status_code == 302
    call.assert_called_once()
    reg.refresh_from_db()
    assert reg.status == Registration.Status.REFUNDED
    body = mail.outbox[-1].body
    assert "$100.0" in body  # refund amount appears in cancellation email


def test_cancel_view_refund_error_shows_message(client, event, tier, user):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.PAID,
    )
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=reg, user=user,
        amount=Decimal("100.00"),
        status=Payment.Status.SUCCEEDED,
        method=Payment.Method.STRIPE,
        stripe_payment_intent_id="pi_test_xyz",
    )
    client.force_login(user)
    with patch(
        "payments.refund.stripe.Refund.create",
        side_effect=RefundError("Stripe API failed"),
    ):
        response = client.post(reverse("registrations:cancel", args=[reg.id]), follow=True)
    # Redirected to confirm with an error message (not the cancelled flag).
    # Django HTML-escapes the apostrophe in "couldn't" so we match a safe substring.
    assert response.status_code == 200
    assert b"process the refund automatically" in response.content
    reg.refresh_from_db()
    assert reg.status == Registration.Status.PAID  # unchanged


# ---- Cancel button on the confirmation page ---------------------------


def test_confirm_page_shows_cancel_button_when_awaiting(client, event, tier, user):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.AWAITING_PAYMENT,
    )
    client.force_login(user)
    response = client.get(reverse("registrations:confirm", args=[reg.id]))
    assert b"Cancel registration" in response.content


def test_confirm_page_hides_cancel_when_cancelled(client, event, tier, user):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.CANCELLED,
    )
    client.force_login(user)
    response = client.get(reverse("registrations:confirm", args=[reg.id]))
    assert b"Cancel registration" not in response.content


# ---- Stripe charge.refunded webhook ------------------------------------


def test_charge_refunded_webhook_marks_refunded(client, event, tier, user):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.PAID,
    )
    payment = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=reg, user=user,
        amount=Decimal("100.00"),
        status=Payment.Status.SUCCEEDED,
        method=Payment.Method.STRIPE,
        stripe_payment_intent_id="pi_test_refund",
        stripe_checkout_session_id="cs_test_refund",
    )
    payload = {
        "id": "evt_refund_1",
        "type": "charge.refunded",
        "data": {"object": {"payment_intent": "pi_test_refund"}},
    }
    with patch(
        "payments.views.stripe.Webhook.construct_event",
        return_value=payload,
    ):
        response = client.post(
            reverse("payments:stripe_webhook"),
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=test",
        )
    assert response.status_code == 200
    payment.refresh_from_db()
    reg.refresh_from_db()
    assert payment.status == Payment.Status.REFUNDED
    assert reg.status == Registration.Status.REFUNDED


def test_charge_refunded_webhook_idempotent(client, event, tier, user):
    """Re-firing on an already-refunded Payment is a no-op."""
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.REFUNDED,
    )
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=reg, user=user,
        amount=Decimal("100.00"),
        status=Payment.Status.REFUNDED,
        method=Payment.Method.STRIPE,
        stripe_payment_intent_id="pi_test_idemp",
    )
    payload = {
        "id": "evt_replay",
        "type": "charge.refunded",
        "data": {"object": {"payment_intent": "pi_test_idemp"}},
    }
    with patch(
        "payments.views.stripe.Webhook.construct_event",
        return_value=payload,
    ):
        response = client.post(
            reverse("payments:stripe_webhook"),
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=test",
        )
    assert response.status_code == 200


@pytest.mark.django_db
def test_charge_refunded_for_unknown_intent_is_noop(client):
    payload = {
        "id": "evt_unknown",
        "type": "charge.refunded",
        "data": {"object": {"payment_intent": "pi_nope"}},
    }
    with patch(
        "payments.views.stripe.Webhook.construct_event",
        return_value=payload,
    ):
        response = client.post(
            reverse("payments:stripe_webhook"),
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=test",
        )
    assert response.status_code == 200


# ---- Event detail page registration badge ------------------------------


def test_event_page_shows_user_registration_status(client, event, tier, user):
    Receipt  # unused-import safety
    Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.AWAITING_PAYMENT,
    )
    client.force_login(user)
    response = client.get(reverse("events:detail", args=[event.slug]))
    assert b"You're registered" in response.content
    assert b"Awaiting payment" in response.content
    # The CTA changes to "View your registration"
    assert b"View your registration" in response.content


def test_event_page_no_badge_when_cancelled(client, event, tier, user):
    Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.CANCELLED,
    )
    client.force_login(user)
    response = client.get(reverse("events:detail", args=[event.slug]))
    assert b"You're registered" not in response.content
    assert b"Register \xe2\x86\x92" in response.content or b"Register" in response.content
