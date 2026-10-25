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

import logging
from decimal import Decimal

import stripe
from django.conf import settings
from django.urls import reverse

from registrations.models import Registration

from .models import Payment

logger = logging.getLogger(__name__)


class CheckoutUnavailable(Exception):
    """Stripe refused or couldn't be reached while opening Checkout.

    Turned into a message and a redirect back by
    ``payments.middleware.CheckoutUnavailableMiddleware`` rather than a server
    error page (task #820): nothing was charged, and trying again is the fix.
    """


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

    try:
        session = _create_session(payment, product_name, product_description,
                                  success_path, cancel_path, customer_email)
    except stripe.error.StripeError as exc:
        # The row was minted for a session that never opened; leaving it
        # PENDING would read to the treasurer as money that might arrive.
        logger.exception("Stripe Checkout failed for payment %s", payment.pk)
        payment.delete()
        raise CheckoutUnavailable(str(exc)) from exc

    payment.stripe_checkout_session_id = session.id
    # Record the mode now (the webhook confirms from the session at completion);
    # keeps test-mode payments out of real accounting.
    payment.livemode = bool(getattr(session, "livemode", True))
    payment.save(update_fields=("stripe_checkout_session_id", "livemode"))
    return session


def _create_session(payment, product_name, product_description,
                    success_path, cancel_path, customer_email):
    return stripe.checkout.Session.create(
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


def create_registration_installment_session(
    installment,
) -> tuple[Payment, stripe.checkout.Session]:
    """Build a Checkout Session for one installment of a plan registration
    (task #501).

    The twin of :func:`create_tuition_session`, minting its own Payment the way
    :func:`create_checkout_session` does — a plan pays the same registration
    several times, so each attempt needs its own row.
    """
    registration = installment.registration
    total = registration.installments.count()

    payment = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=registration,
        user=registration.user,
        amount=installment.amount,
        method=Payment.Method.STRIPE,
        status=Payment.Status.PENDING,
        registration_installment=installment,
    )

    session = _make_session(
        payment=payment,
        product_name=registration.event.title,
        product_description=(
            f"Payment {installment.sequence} of {total} "
            f"(${registration.quoted_amount} total)"
        ),
        success_path=(
            reverse("registrations:confirm", args=[registration.id])
            + "?stripe=success"
        ),
        cancel_path=(
            reverse("registrations:confirm", args=[registration.id])
            + "?stripe=cancelled"
        ),
    )
    return payment, session


def create_per_class_session(
    registration: Registration,
) -> tuple[Payment, stripe.checkout.Session]:
    """Checkout for a per-class registration's open balance (task #811).

    The Payment points at the registration through ``per_class_registration``,
    never ``registration``, so ``complete_payment`` only issues the receipt:
    the money sweeps onto the class charges in the ledger like any other
    registration payment.
    """
    from django.utils import timezone

    from events.per_class import open_charges

    rows = open_charges(registration)
    amount = sum((remaining for _c, remaining in rows), Decimal("0"))
    if amount <= Decimal("0"):
        raise ValueError(
            f"Nothing to pay on per-class registration {registration.id}."
        )
    days = []
    for charge, _remaining in rows:
        day = timezone.localdate(charge.class_attendance.session.start_at)
        days.append(f"{day:%b} {day.day}")
    payment = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        per_class_registration=registration,
        user=registration.user,
        amount=amount,
        method=Payment.Method.STRIPE,
        status=Payment.Status.PENDING,
    )
    noun = "class" if len(days) == 1 else "classes"
    session = _make_session(
        payment=payment,
        product_name=registration.event.title,
        product_description=f"{len(days)} {noun}: {', '.join(days)}",
        success_path=(
            reverse("registrations:confirm", args=[registration.id])
            + "?stripe=success#classes"
        ),
        cancel_path=(
            reverse("registrations:confirm", args=[registration.id])
            + "?stripe=cancelled#classes"
        ),
    )
    return payment, session


def create_dues_session(payment: Payment) -> stripe.checkout.Session:
    """Build a Checkout Session for membership dues (REG-12).

    The period name goes in the description because dues can now be paid for a
    year that has not started (task #625) — without it the receipt for an
    early payment would not say which year it bought.
    """
    year = payment.dues_period.name if payment.dues_period_id else None
    description = "Annual membership in the Lacanian School of Psychoanalysis"
    return _make_session(
        payment=payment,
        product_name="LSP membership dues",
        product_description=(
            f"{description} — {year}" if year else description
        ),
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
        success_path=reverse("formation:formation") + "?tab=account&stripe=success",
        cancel_path=reverse("formation:formation") + "?tab=account&stripe=cancelled",
    )
