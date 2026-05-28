"""Transactional emails for payments and registrations (REG-7, REG-8, REG-9).

All outgoing transactional mail sends from ``DEFAULT_FROM_EMAIL``
(``no-reply@…`` — keeps the sending domain stable for SES/DKIM) with a
``Reply-To: SUPPORT_EMAIL`` (``website@lacanschool.org`` by default) so
that a recipient clicking *Reply* in their mail client reaches a human.
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils import timezone

from registrations.models import Registration

from .models import Payment


def _send(*, subject: str, body: str, to: list[str]) -> None:
    """Send a transactional email with the right From and Reply-To headers."""
    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=to,
        reply_to=[settings.SUPPORT_EMAIL],
    )
    msg.send(fail_silently=False)


def send_registration_confirmation(registration: Registration) -> None:
    """Send the confirmation email (REG-9), releasing access_info if PAID (REG-8)."""
    subject = f"Registration confirmed: {registration.event.title}"
    body = render_to_string(
        "payments/email/confirmation.txt",
        {
            "registration": registration,
            "support_email": settings.SUPPORT_EMAIL,
            "site_base_url": settings.SITE_BASE_URL,
        },
    )
    _send(subject=subject, body=body, to=[registration.user.email])


def send_receipt(payment: Payment) -> None:
    """Send the receipt email (REG-7) and stamp ``emailed_at``."""
    receipt = payment.receipt
    subject = f"Receipt {receipt.receipt_number} — Lacanian School of Psychoanalysis"
    body = render_to_string(
        "payments/email/receipt.txt",
        {
            "payment": payment,
            "receipt": receipt,
            "support_email": settings.SUPPORT_EMAIL,
        },
    )
    to_email = payment.recipient_email
    if not to_email:
        # Defensive — should never happen for a paid Payment.
        return
    _send(subject=subject, body=body, to=[to_email])
    receipt.emailed_at = timezone.now()
    receipt.save(update_fields=("emailed_at",))


def send_payment_receipt(payment: Payment) -> None:
    """Receipt-only send for dues / donations (no registration, no access_info).

    Existing :func:`send_receipt` would suffice but this is a thin wrapper
    so callers can express intent. Idempotency lives at the call site —
    the webhook only calls this once per Payment via the SUCCEEDED guard.
    """
    if hasattr(payment, "receipt"):
        send_receipt(payment)


def send_paid_emails(registration: Registration) -> None:
    """Send both the confirmation and (if there's a paid Payment) the receipt."""
    send_registration_confirmation(registration)
    paid = registration.payments.filter(
        status=Payment.Status.SUCCEEDED,
        receipt__isnull=False,
    ).order_by("-paid_at").first()
    if paid is not None:
        send_receipt(paid)


def send_dues_reminder(user, period) -> None:
    """Weekly reminder email to an unpaid dues-obligated user (REG-12)."""
    subject = f"Reminder: {period.name} dues are due"
    body = render_to_string(
        "payments/email/dues_reminder.txt",
        {
            "user": user,
            "period": period,
            "support_email": settings.SUPPORT_EMAIL,
            "site_base_url": settings.SITE_BASE_URL,
        },
    )
    _send(subject=subject, body=body, to=[user.email])


def send_cancellation_email(registration: Registration, refund=None) -> None:
    """Notify the participant that their registration was cancelled.

    Includes refund detail if ``refund`` (a Stripe ``Refund`` object or a
    dict-like with ``amount`` in cents) is provided.
    """
    refund_amount = None
    if refund is not None:
        # Stripe Refund: amount is in cents.
        try:
            refund_amount = (refund["amount"] / 100) if "amount" in refund else None
        except (TypeError, KeyError):
            refund_amount = None
    subject = f"Registration cancelled: {registration.event.title}"
    body = render_to_string(
        "payments/email/cancellation.txt",
        {
            "registration": registration,
            "refund_amount": refund_amount,
            "support_email": settings.SUPPORT_EMAIL,
            "site_base_url": settings.SITE_BASE_URL,
        },
    )
    _send(subject=subject, body=body, to=[registration.user.email])
