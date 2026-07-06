"""Stripe Checkout integration (architecture § 6.3).

Three entry points — all build on the same generic ``_make_session`` so
the webhook handler stays uniform:

- ``create_checkout_session(registration)`` — event registration (REG-3).
- ``create_dues_session(payment)`` — annual membership dues (REG-12).
- ``create_donation_session(payment)`` — donation (REG-13).

Each creates a Stripe ``Checkout.Session`` whose ``id`` is stored on the
``Payment`` as the natural webhook idempotency key.
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


def _make_session(
    *,
    payment: Payment,
    product_name: str,
    product_description: str,
    success_path: str,
    cancel_path: str,
    customer_email: str | None = None,
) -> stripe.checkout.Session:
    """Generic Checkout Session builder.

    Caller owns the Payment row's lifecycle (create with status=PENDING,
    set ``user`` and ``amount``, etc.). We attach the Session id to the
    Payment for idempotent webhook lookup.

    ``automatic_tax`` is intentionally omitted — LSP is a non-profit
    selling intangible educational services / membership and is not
    expected to charge sales tax. Verify in the Stripe account that
    Stripe Tax is OFF before launch.
    """
    _configure()
    if payment.amount <= Decimal("0"):
        raise ValueError(
            f"Refusing to create a Stripe session for a non-positive amount "
            f"(payment {payment.id}: ${payment.amount})."
        )

    session = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[
            {
                "quantity": 1,
                "price_data": {
                    "currency": "usd",
                    "unit_amount": int(payment.amount * 100),
                    "product_data": {
                        "name": product_name[:127],  # Stripe caps name at 127
                        "description": product_description[:500] if product_description else None,
                    },
                },
            },
        ],
        customer_email=customer_email or (payment.user.email if payment.user else None),
        client_reference_id=str(payment.id),
        success_url=settings.SITE_BASE_URL + success_path,
        cancel_url=settings.SITE_BASE_URL + cancel_path,
        metadata={
            "payment_id": str(payment.id),
            "payment_type": payment.payment_type,
        },
    )

    payment.stripe_checkout_session_id = session.id
    # Record the mode now (the webhook confirms from the session at completion);
    # keeps test-mode payments out of real accounting.
    payment.livemode = bool(getattr(session, "livemode", True))
    payment.save(update_fields=("stripe_checkout_session_id", "livemode"))
    return session


def create_checkout_session(
    registration: Registration,
) -> tuple[Payment, stripe.checkout.Session]:
    """Build a Checkout Session for an event registration (REG-3)."""
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

    session = _make_session(
        payment=payment,
        product_name=registration.event.title,
        product_description=(
            f"{registration.price_tier.get_audience_display()} "
            f"— {registration.event.start_date.isoformat()} to "
            f"{registration.event.end_date.isoformat()}"
        ),
        success_path=(
            reverse("registrations:confirm", args=[registration.id])
            + "?stripe=success"
        ),
        cancel_path=(
            reverse("events:detail", args=[registration.event.slug])
            + "?stripe=cancelled"
        ),
    )
    return payment, session


def create_dues_session(payment: Payment) -> stripe.checkout.Session:
    """Build a Checkout Session for membership dues (REG-12)."""
    return _make_session(
        payment=payment,
        product_name="LSP membership dues",
        product_description="Annual membership in the Lacanian School of Psychoanalysis",
        success_path=reverse("payments:thanks", args=[payment.id]) + "?stripe=success",
        cancel_path="/?stripe=cancelled",
    )


def create_donation_session(
    payment: Payment, *, customer_email: str | None = None
) -> stripe.checkout.Session:
    """Build a Checkout Session for a donation (REG-13). ``customer_email``
    overrides ``payment.user.email`` for anonymous donations."""
    return _make_session(
        payment=payment,
        product_name="Donation to the Lacanian School of Psychoanalysis",
        product_description="Thank you for your support.",
        success_path=reverse("payments:thanks", args=[payment.id]) + "?stripe=success",
        cancel_path="/?stripe=cancelled",
        customer_email=customer_email,
    )


def create_tuition_session(payment: Payment) -> stripe.checkout.Session:
    """Build a Checkout Session for a tuition installment payment (M7.5).

    The Payment must already be linked to a TuitionInstallment; the
    period name appears in the product description for receipt clarity.
    """
    installment = payment.tuition_installment
    if installment is None:
        raise ValueError(
            f"Refusing to create a Stripe session for tuition Payment {payment.id}: "
            "no TuitionInstallment is linked."
        )
    enrollment = installment.enrollment
    period_name = enrollment.tuition_period.name
    total_installments = enrollment.installments.count()
    if total_installments == 1:
        description = f"Annual tuition for {period_name}"
    else:
        description = (
            f"Tuition installment {installment.sequence} of "
            f"{total_installments} for {period_name}"
        )
    return _make_session(
        payment=payment,
        product_name=f"LSP tuition — {period_name}",
        product_description=description,
        success_path=reverse("formation:formation") + "?tab=tuition&stripe=success",
        cancel_path=reverse("formation:formation") + "?tab=tuition&stripe=cancelled",
    )
