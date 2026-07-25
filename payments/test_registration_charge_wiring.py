"""The registration-charge hooks are actually wired to the real surfaces
(task #443).

``test_registration_charges.py`` covers the hook functions themselves; these
tests drive the surfaces a human or Stripe actually touches — the comp admin
action, the member's self-service cancel, the Stripe refund webhook, and the
treasurer's offline-refund action — and assert the charge moved with them.
Without these, a hook could be deleted from a call site and every existing
test would still pass.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.admin.sites import site
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory
from django.urls import reverse

from accounts.models import User
from events.models import Audience, Event, PriceTier
from payments.models import Charge, Payment
from payments.operations import complete_payment
from registrations.models import Registration

pytestmark = pytest.mark.django_db


@pytest.fixture
def member():
    return User.objects.create_user(email="wire@x.test", password="x")


@pytest.fixture
def event():
    return Event.objects.create(
        title="Seminar W", slug="seminar-w",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
        published=True, status=Event.Status.OPEN,
    )


@pytest.fixture
def registration(member, event):
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("60.00"),
    )
    return Registration.objects.create(
        user=member, event=event, price_tier=tier,
        quoted_amount=Decimal("60.00"),
    )


def _paid(registration, **kw):
    """Settle the registration through the real payment path, so it carries a
    minted OPEN charge exactly as production would."""
    kw.setdefault("method", Payment.Method.STRIPE)
    payment = Payment.objects.create(
        user=registration.user, payment_type=Payment.Type.REGISTRATION,
        registration=registration, amount=registration.quoted_amount, **kw,
    )
    complete_payment(payment)
    registration.refresh_from_db()
    return payment


# ------------------------------------------------------ comp (admin action)


def test_comp_admin_action_waives_the_charge(member, registration):
    admin_user = User.objects.create_superuser(email="wire-admin@x.test",
                                               password="x")
    rf = RequestFactory()
    request = rf.request()
    request.user = admin_user
    request.session = {}
    request._messages = FallbackStorage(request)

    model_admin = site._registry[Registration]
    model_admin.comp_selected_registrations(
        request, Registration.objects.filter(pk=registration.pk))

    registration.refresh_from_db()
    assert registration.status == Registration.Status.COMPED
    charge = Charge.objects.get(registration=registration)
    assert charge.status == Charge.Status.WAIVED
    assert charge.amount == Decimal("60.00")


# ------------------------------------------------- cancel (member, in-site)


def test_member_cancel_voids_the_charge(client, member, registration, monkeypatch):
    """The self-service cancel refunds through Stripe and must take the
    charge off the member's ledger with it."""
    _paid(registration, stripe_payment_intent_id="pi_wire_cancel")
    # Don't call Stripe: reg.cancel() refunds through payments.refund.
    monkeypatch.setattr("payments.refund.refund_payment", lambda payment: None)

    client.force_login(member)
    resp = client.post(reverse("registrations:cancel", args=[registration.id]))
    assert resp.status_code == 302

    charge = Charge.objects.get(registration=registration)
    assert charge.status == Charge.Status.VOID
    assert "cancelled by the member" in charge.notes


# ------------------------------------------------- refund (Stripe webhook)


def test_stripe_refund_webhook_voids_the_charge(member, registration):
    from payments.views import _handle_charge_refunded

    payment = _paid(registration, stripe_payment_intent_id="pi_wire_refund")
    assert Charge.objects.get(registration=registration).status == Charge.Status.OPEN

    _handle_charge_refunded({"payment_intent": "pi_wire_refund"})

    payment.refresh_from_db()
    registration.refresh_from_db()
    assert payment.status == Payment.Status.REFUNDED
    assert registration.status == Registration.Status.REFUNDED
    charge = Charge.objects.get(registration=registration)
    assert charge.status == Charge.Status.VOID
    assert "Stripe refund" in charge.notes


# ------------------------------------------ offline refund (treasurer view)


def test_treasurer_offline_refund_voids_the_charge(client, member, registration):
    treasurer = User.objects.create_user(
        email="wire-tr@x.test", password="x", is_staff=True)
    payment = _paid(registration, method=Payment.Method.OFFLINE)
    client.force_login(treasurer)

    resp = client.post(reverse("treasurer_payment_refund", args=[payment.id]))
    assert resp.status_code == 302

    charge = Charge.objects.get(registration=registration)
    assert charge.status == Charge.Status.VOID
    assert "Offline refund" in charge.notes
