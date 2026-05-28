"""Stripe refund handling (REG-16).

One responsibility: turn a successful Stripe ``Payment`` into a refunded
one by calling Stripe's Refund API and updating our DB row. Idempotent
on a Payment that's already REFUNDED.
"""

from __future__ import annotations

import stripe
from django.conf import settings

from .models import Payment


def _configure() -> None:
    stripe.api_key = settings.STRIPE_SECRET_KEY


class RefundError(RuntimeError):
    """Raised when a payment can't be refunded (wrong method, no intent, etc.)."""


def refund_payment(payment: Payment):
    """Issue a full Stripe refund for ``payment``; mark the row REFUNDED.

    Returns the Stripe ``Refund`` object on success, or ``None`` if the
    payment is already REFUNDED (idempotent no-op). Raises ``RefundError``
    if the payment is not eligible for automatic refund (offline method,
    missing payment_intent_id, etc.).
    """
    if payment.status == Payment.Status.REFUNDED:
        return None
    if payment.method != Payment.Method.STRIPE:
        raise RefundError(
            "Cannot auto-refund a non-Stripe payment; record the refund manually."
        )
    if not payment.stripe_payment_intent_id:
        raise RefundError(
            "Payment has no stripe_payment_intent_id; cannot identify the charge."
        )

    _configure()
    refund = stripe.Refund.create(payment_intent=payment.stripe_payment_intent_id)
    payment.status = Payment.Status.REFUNDED
    payment.save(update_fields=("status",))
    return refund
