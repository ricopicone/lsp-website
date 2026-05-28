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

from registrations.models import Registration

from .emails import send_paid_emails, send_payment_receipt
from .models import Payment, Receipt

logger = logging.getLogger(__name__)


def complete_payment(payment: Payment) -> None:
    """Apply all success-side-effects: status, registration flip, receipt, emails.

    Idempotent. Email failures don't roll back the DB transition.
    """
    with transaction.atomic():
        payment.mark_succeeded()
        if payment.registration_id:
            Registration.objects.filter(
                pk=payment.registration_id,
                status=Registration.Status.AWAITING_PAYMENT,
            ).update(status=Registration.Status.PAID)
        if not hasattr(payment, "receipt"):
            Receipt.create_for_payment(payment)

    # Emails outside the DB transaction so failures don't roll back.
    try:
        if payment.registration_id:
            payment.registration.refresh_from_db()
            send_paid_emails(payment.registration)
        else:
            send_payment_receipt(payment)
    except Exception:
        logger.exception(
            "Failed to send post-payment emails for payment %s; "
            "DB state retained.",
            payment.id,
        )
