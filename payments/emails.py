"""Transactional emails for payments and registrations (REG-7, REG-8, REG-9)."""

from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from registrations.models import Registration

from .models import Payment


def send_registration_confirmation(registration: Registration) -> None:
    """Send the confirmation email (REG-9), releasing access_info if PAID (REG-8)."""
    subject = f"Registration confirmed: {registration.event.title}"
    body = render_to_string(
        "payments/email/confirmation.txt",
        {"registration": registration},
    )
    send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[registration.user.email],
        fail_silently=False,
    )


def send_receipt(payment: Payment) -> None:
    """Send the receipt email (REG-7) and stamp ``emailed_at``."""
    receipt = payment.receipt  # raises Receipt.DoesNotExist if missing
    subject = f"Receipt {receipt.receipt_number} — Lacanian School of Psychoanalysis"
    body = render_to_string(
        "payments/email/receipt.txt",
        {"payment": payment, "receipt": receipt},
    )
    send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[payment.user.email] if payment.user else [],
        fail_silently=False,
    )
    receipt.emailed_at = timezone.now()
    receipt.save(update_fields=("emailed_at",))


def send_paid_emails(registration: Registration) -> None:
    """Send both the confirmation and (if there's a paid Payment) the receipt.

    Idempotent on its callers: re-sending is safe but wasteful, so the
    webhook handler should only call this on first transition to PAID.
    """
    send_registration_confirmation(registration)
    # Find the most recent successful payment to attach a receipt to (there
    # should be at most one for now; partials/refunds come later).
    paid = registration.payments.filter(
        status=Payment.Status.SUCCEEDED,
        receipt__isnull=False,
    ).order_by("-paid_at").first()
    if paid is not None:
        send_receipt(paid)
