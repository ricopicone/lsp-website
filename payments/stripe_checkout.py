"""Stripe Checkout integration (architecture § 6.3).

One responsibility: turn a ``Registration`` (with its already-resolved
``quoted_amount``) into a Stripe Checkout Session, recording a ``Payment``
row keyed to the session id for webhook idempotency.

The webhook handler in :mod:`payments.views` consumes the resulting
``checkout.session.completed`` event.
"""

from __future__ import annotations

from decimal import Decimal

import stripe
from django.conf import settings
from django.urls import reverse

from registrations.models import Registration

from .models import Payment


def _configure() -> None:
    stripe.api_key = settings.STRIPE_SECRET_KEY


def create_checkout_session(registration: Registration) -> tuple[Payment, stripe.checkout.Session]:
    """Create a Stripe Checkout Session for ``registration``.

    Creates a Payment row (status=PENDING, method=STRIPE), then a Stripe
    Session with the Payment row's id as ``client_reference_id`` and the
    Session id stored back on the Payment row for idempotent webhook lookup.

    The caller is expected to redirect to the returned Session's ``url``.
    """
    _configure()
    if registration.quoted_amount <= Decimal("0"):
        raise ValueError(
            "Refusing to create a Stripe session for a $0 registration "
            "(should have short-circuited to PAID locally)."
        )

    payment = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=registration,
        user=registration.user,
        amount=registration.quoted_amount,
        method=Payment.Method.STRIPE,
        status=Payment.Status.PENDING,
    )

    session = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[
            {
                "quantity": 1,
                "price_data": {
                    "currency": "usd",
                    "unit_amount": int(registration.quoted_amount * 100),
                    "product_data": {
                        "name": registration.event.title,
                        "description": (
                            f"{registration.price_tier.get_audience_display()} "
                            f"— {registration.event.start_date.isoformat()} to "
                            f"{registration.event.end_date.isoformat()}"
                        )[:500],
                    },
                },
            },
        ],
        customer_email=registration.user.email,
        client_reference_id=str(payment.id),
        success_url=(
            settings.SITE_BASE_URL
            + reverse("registrations:confirm", args=[registration.id])
            + "?stripe=success"
        ),
        cancel_url=(
            settings.SITE_BASE_URL
            + reverse("events:detail", args=[registration.event.slug])
            + "?stripe=cancelled"
        ),
        metadata={
            "registration_id": str(registration.id),
            "payment_id": str(payment.id),
        },
    )

    payment.stripe_checkout_session_id = session.id
    payment.save(update_fields=("stripe_checkout_session_id",))
    return payment, session
