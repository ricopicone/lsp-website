"""Side-effect orchestration for Payment state transitions (REG-14).

``complete_payment(payment)`` is the single source of truth for what
happens when a Payment becomes SUCCEEDED — used by:

- the Stripe webhook handler (after ``checkout.session.completed``)
- admin actions for offline / manual payments

Idempotent: safe to call on a Payment that's already SUCCEEDED.
"""

from __future__ import annotations

import logging

from django.db import transaction

from accounts.models import Source
from registrations.models import Registration

from . import notifications as notify_payments
from .models import Payment, Receipt

logger = logging.getLogger(__name__)


def complete_payment(payment: Payment) -> None:
    """Apply all success-side-effects: status, registration flip, receipt, emails.

    For TUITION payments, additionally mark the linked installment as paid
    and flip the enrollment to PAID_IN_FULL when all of its installments are
    paid. Idempotent. Email failures don't roll back the DB transition.
    """
    with transaction.atomic():
        payment.mark_succeeded()
        # A completed Stripe payment is real money confirmed → verified
        # provenance. Offline/manual completions keep their existing source
        # (STAFF by default).
        if payment.method == Payment.Method.STRIPE and payment.source != Source.VERIFIED:
            payment.source = Source.VERIFIED
            payment.save(update_fields=("source",))
        if payment.registration_id:
            Registration.objects.filter(
                pk=payment.registration_id,
                status=Registration.Status.AWAITING_PAYMENT,
            ).update(status=Registration.Status.PAID)
        if payment.registration_id and payment.amount > 0:
            from .charges import mint_registration_charge
            mint_registration_charge(payment)
        if payment.payment_type == Payment.Type.TUITION and payment.tuition_installment_id:
            _apply_tuition_payment_success(payment)
        if not hasattr(payment, "receipt"):
            Receipt.create_for_payment(payment)

    # Notifications + emails outside the DB transaction so failures don't roll
    # back. Confirmation and receipt are email-locked categories — they always
    # email, and now also raise an in-app bell row.
    try:
        if payment.registration_id:
            payment.registration.refresh_from_db()
            notify_payments.registration_confirmed(payment.registration)
            notify_payments.payment_receipt(payment)
        else:
            notify_payments.payment_receipt(payment)
    except Exception:
        logger.exception(
            "Failed to send post-payment emails for payment %s; "
            "DB state retained.",
            payment.id,
        )


def _apply_tuition_payment_success(payment: Payment) -> None:
    """Mark the installment paid; flip enrollment to PAID_IN_FULL if all paid.

    Idempotent — re-marking a paid installment is a no-op, and flipping
    an already-paid_in_full enrollment is a no-op.
    """
    from .models import TuitionEnrollment, TuitionInstallment
    installment = TuitionInstallment.objects.select_related(
        "enrollment",
    ).get(pk=payment.tuition_installment_id)
    installment.mark_paid()
    enrollment = installment.enrollment
    unpaid_remaining = enrollment.installments.filter(paid=False).exists()
    if not unpaid_remaining and enrollment.status != TuitionEnrollment.Status.PAID_IN_FULL:
        enrollment.status = TuitionEnrollment.Status.PAID_IN_FULL
        enrollment.save(update_fields=("status",))
