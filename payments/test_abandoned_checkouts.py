"""Abandoned Stripe checkouts (task #474).

A Checkout Session expires unpaid after ~24h. Until now nothing told the site,
so the ``Payment`` row sat at PENDING forever and read to the treasurer as
"maybe this went through". Two paths close that: the ``checkout.session.expired``
webhook (immediate) and ``manage.py reconcile_stripe_pending`` (the safety net
that also settles a checkout whose *completed* webhook we never received).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from events.models import Audience, Event, PriceTier
from payments.models import Payment
from registrations.models import Registration


@pytest.fixture
def pending_payment(db):
    user = User.objects.create_user(email="abandon@example.com")
    event = Event.objects.create(
        title="X", slug="x",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("250.00"),
    )
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier, quoted_amount=Decimal("250.00"),
    )
    return Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=reg,
        user=user,
        amount=Decimal("250.00"),
        method=Payment.Method.STRIPE,
        status=Payment.Status.PENDING,
        stripe_checkout_session_id="cs_test_expired",
    )


def _post_expired(client, session_id: str):
    payload = {
        "id": "evt_test_expired",
        "type": "checkout.session.expired",
        "data": {"object": {"id": session_id}},
    }
    body = json.dumps(payload).encode("utf-8")
    with patch(
        "payments.views.stripe.Webhook.construct_event", return_value=payload,
    ):
        return client.post(
            reverse("payments:stripe_webhook"),
            data=body,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=test",
        )


# --- webhook ---------------------------------------------------------------

@override_settings(STRIPE_WEBHOOK_SECRET="whsec_test")
def test_expired_webhook_abandons_the_payment(client, pending_payment):
    assert _post_expired(client, "cs_test_expired").status_code == 200

    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.ABANDONED
    assert "expired" in pending_payment.notes.lower()


@override_settings(STRIPE_WEBHOOK_SECRET="whsec_test")
def test_expired_webhook_leaves_the_registration_open(client, pending_payment):
    """The member can still pay — abandoning the checkout is not a cancellation."""
    reg = pending_payment.registration
    assert _post_expired(client, "cs_test_expired").status_code == 200

    reg.refresh_from_db()
    assert reg.status == Registration.Status.AWAITING_PAYMENT


@override_settings(STRIPE_WEBHOOK_SECRET="whsec_test")
def test_expired_webhook_never_touches_a_succeeded_payment(client, pending_payment):
    """Stripe can deliver events out of order — a paid row must stay paid."""
    pending_payment.status = Payment.Status.SUCCEEDED
    pending_payment.save(update_fields=["status"])

    assert _post_expired(client, "cs_test_expired").status_code == 200

    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.SUCCEEDED


@override_settings(STRIPE_WEBHOOK_SECRET="whsec_test")
def test_expired_webhook_for_unknown_session_is_a_no_op(client, pending_payment):
    assert _post_expired(client, "cs_test_nosuch").status_code == 200

    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.PENDING


# --- the sweep -------------------------------------------------------------

class _FakeSession(dict):
    """Stands in for a ``stripe.checkout.Session`` (bracket access + ``in``)."""


def _run_sweep(sessions: dict, **opts):
    """Run the command with Stripe's session lookup stubbed."""
    def _retrieve(session_id, *a, **kw):
        return _FakeSession(sessions[session_id])

    out = StringIO()
    with patch("payments.stripe_sync.stripe.checkout.Session.retrieve", _retrieve):
        call_command("reconcile_stripe_pending", stdout=out, **opts)
    return out.getvalue()


def _age(payment, hours):
    Payment.objects.filter(pk=payment.pk).update(
        created_at=timezone.now() - timedelta(hours=hours),
    )


def test_sweep_abandons_an_expired_session(pending_payment):
    _age(pending_payment, 30)
    _run_sweep({"cs_test_expired": {
        "id": "cs_test_expired", "status": "expired", "payment_status": "unpaid",
    }})

    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.ABANDONED


def test_sweep_settles_a_checkout_whose_webhook_we_missed(pending_payment):
    """The real payoff: money that arrived while the webhook was down."""
    _age(pending_payment, 30)
    _run_sweep({"cs_test_expired": {
        "id": "cs_test_expired", "status": "complete", "payment_status": "paid",
        "payment_intent": "pi_recovered",
    }})

    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.SUCCEEDED
    assert pending_payment.stripe_payment_intent_id == "pi_recovered"
    pending_payment.registration.refresh_from_db()
    assert pending_payment.registration.status == Registration.Status.PAID


def test_sweep_leaves_a_checkout_still_in_flight_alone(pending_payment):
    """Inside the age window the member may still be typing their card in."""
    _age(pending_payment, 2)
    _run_sweep({"cs_test_expired": {
        "id": "cs_test_expired", "status": "open", "payment_status": "unpaid",
    }})

    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.PENDING


def test_sweep_leaves_an_open_session_past_the_window_alone(pending_payment):
    """Old but still open (Stripe hasn't expired it yet) — not ours to judge."""
    _age(pending_payment, 30)
    _run_sweep({"cs_test_expired": {
        "id": "cs_test_expired", "status": "open", "payment_status": "unpaid",
    }})

    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.PENDING


def test_sweep_dry_run_writes_nothing(pending_payment):
    _age(pending_payment, 30)
    out = _run_sweep({"cs_test_expired": {
        "id": "cs_test_expired", "status": "expired", "payment_status": "unpaid",
    }}, dry_run=True)

    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.PENDING
    assert "abandon" in out.lower()


def test_sweep_ignores_offline_payments(pending_payment):
    """An offline row is a treasurer's manual record — Stripe knows nothing."""
    _age(pending_payment, 30)
    pending_payment.method = Payment.Method.OFFLINE
    pending_payment.stripe_checkout_session_id = ""
    pending_payment.save(update_fields=["method", "stripe_checkout_session_id"])

    _run_sweep({})      # a lookup would KeyError — assert none happens

    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.PENDING


# --- what the treasurer sees -----------------------------------------------

def test_payments_tab_badges_and_filters_abandoned(client, pending_payment, db):
    """A treasurer must be able to tell "never finished" from "still coming"."""
    staff = User.objects.create_user(
        email="tr474@example.com", password="x", is_staff=True,
    )
    pending_payment.status = Payment.Status.ABANDONED
    pending_payment.save(update_fields=["status"])
    client.force_login(staff)

    page = client.get(reverse("treasurer_payments")).content.decode()
    assert "Abandoned" in page
    assert 'value="abandoned"' in page       # the status filter offers it

    filtered = client.get(
        reverse("treasurer_payments"), {"status": "abandoned"},
    ).content.decode()
    assert "$250.00" in filtered


# --- accounting ------------------------------------------------------------

def test_abandoned_payments_do_not_count_as_credit(pending_payment):
    """An abandoned checkout moved no money — the ledger must ignore it."""
    from payments import ledger

    pending_payment.status = Payment.Status.ABANDONED
    pending_payment.save(update_fields=["status"])

    account = ledger.member_account(pending_payment.user)
    assert account["paid"] == Decimal("0.00")
