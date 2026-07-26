"""Settling PENDING Stripe payments against Stripe's own view (task #474).

A ``Payment`` row is created the moment a member is sent to Checkout, so a
PENDING row means only "we asked Stripe for money" — never that money is on the
way. Sessions expire unpaid after ~24h and, before this module, nothing ever
told the site: stale PENDING rows accumulated on the treasurer's Payments tab
(one per abandoned attempt, since every retry mints a fresh row) reading as
"this might have gone through".

Two callers share the logic here:

- ``payments.views._handle_checkout_expired`` — the ``checkout.session.expired``
  webhook, which settles an abandonment within seconds.
- ``manage.py reconcile_stripe_pending`` — the nightly sweep, which re-asks
  Stripe about every stale PENDING row. That covers the case the webhook
  cannot: a *completed* checkout whose delivery we never received. Money that
  actually arrived is settled with the same ``complete_payment`` chain the
  webhook uses, so a missed webhook can no longer silently cost the school a
  registration.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Payment

logger = logging.getLogger(__name__)

#: How long a payment may sit PENDING before the sweep asks Stripe about it.
#: Stripe's Checkout Sessions expire 24h after creation, so anything younger
#: may still be a member with the payment page open.
STALE_AFTER_HOURS = 25


def abandon_payment(payment: Payment, *, reason: str) -> bool:
    """Mark a never-completed checkout ABANDONED. Returns True if it changed.

    Only ever moves a PENDING row: Stripe can deliver events out of order, and
    a paid row must stay paid.
    """
    if payment.status != Payment.Status.PENDING:
        return False
    payment.status = Payment.Status.ABANDONED
    payment.add_note(reason, save=False)
    payment.save(update_fields=("status", "notes"))
    logger.info("Payment %s marked abandoned: %s", payment.pk, reason)
    return True


def settle_from_session(payment: Payment, session) -> str:
    """Bring ``payment`` in line with the Stripe ``session``.

    Returns what happened: ``"abandoned"``, ``"completed"``, or ``""`` (left
    alone). ``session`` may be a ``stripe.checkout.Session`` or a plain dict —
    use bracket access only, ``StripeObject`` has no ``dict.get``.
    """
    if payment.status != Payment.Status.PENDING:
        return ""

    status = session["status"] if "status" in session else ""
    paid = (session["payment_status"] if "payment_status" in session else "") == "paid"

    if paid or status == "complete":
        _complete(payment, session)
        return "completed"
    if status == "expired":
        abandon_payment(
            payment,
            reason="Stripe checkout expired unpaid — no payment was taken.",
        )
        return "abandoned"
    # Still open: Stripe hasn't given up on it, so neither do we.
    return ""


def _complete(payment: Payment, session) -> None:
    """Run the same success chain the webhook does, for money we only learn
    about at sweep time."""
    from .views import complete_payment

    with transaction.atomic():
        fields = []
        intent_id = session["payment_intent"] if "payment_intent" in session else None
        if intent_id and not payment.stripe_payment_intent_id:
            payment.stripe_payment_intent_id = intent_id
            fields.append("stripe_payment_intent_id")
        payment.add_note(
            "Settled by the pending-payment sweep — Stripe reports this "
            "checkout as paid (the completion webhook never arrived).",
            save=False,
        )
        fields.append("notes")
        payment.save(update_fields=fields)

    complete_payment(payment)


def stale_pending_payments(*, hours: int = STALE_AFTER_HOURS):
    """PENDING Stripe payments old enough that Stripe should have a verdict.

    Offline rows are excluded — they are a treasurer's manual record awaiting
    the *Apply payment success* action, and Stripe knows nothing about them.
    """
    return (
        Payment.objects.filter(
            status=Payment.Status.PENDING,
            method=Payment.Method.STRIPE,
            created_at__lt=timezone.now() - timedelta(hours=hours),
        )
        .exclude(stripe_checkout_session_id="")
        .order_by("created_at")
    )


def fetch_session(session_id: str):
    """Retrieve a Checkout Session (own function so tests can patch one seam)."""
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe.checkout.Session.retrieve(session_id)
