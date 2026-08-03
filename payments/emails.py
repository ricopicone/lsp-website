"""Transactional emails for payments and registrations (REG-7, REG-8, REG-9).

All outgoing transactional mail sends from ``DEFAULT_FROM_EMAIL``
(``no-reply@…`` — keeps the sending domain stable for SES/DKIM) with a
``Reply-To: SUPPORT_EMAIL`` (``website@lacanschool.org`` by default) so
that a recipient clicking *Reply* in their mail client reaches a human.
"""

from __future__ import annotations

import contextlib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from registrations.models import Registration

from .models import Payment


def _send(*, subject: str, body: str, to: list[str], sender: str = "LSP Registration") -> None:
    """Send a transactional email with the right From and Reply-To headers.

    ``sender`` is the friendly From display name (most payments mail is event
    registration; receipts and dues/tuition reminders pass "LSP Treasurer")."""
    from core.email import school_from

    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=school_from(sender),
        to=to,
        reply_to=[settings.SUPPORT_EMAIL],
    )
    msg.send(fail_silently=False)


def _recipient_timezone(user) -> contextlib.AbstractContextManager:
    """Context manager that activates the recipient user's preferred TZ
    while the body renders. Falls back to project default for users
    with no preference (or no user object).

    Cron-sent emails don't have a request, so the middleware's active
    TZ is the project default — without this wrapper, every recipient
    would see PT regardless of their preference.
    """
    tz_name = getattr(getattr(user, "profile", None), "timezone", "") or ""
    if not tz_name:
        return contextlib.nullcontext()
    try:
        return timezone.override(ZoneInfo(tz_name))
    except ZoneInfoNotFoundError:
        return contextlib.nullcontext()


def send_registration_confirmation(registration: Registration) -> None:
    """Send the confirmation email (REG-9), releasing access_info if PAID/COMPED."""
    from django.urls import reverse

    from video.services import daily_enabled

    subject = f"Registration confirmed: {registration.event.title}"
    has_access = registration.status in (
        Registration.Status.PAID,
        Registration.Status.COMPED,
    )
    room_url = ""
    if has_access and daily_enabled():
        room_url = settings.SITE_BASE_URL.rstrip("/") + reverse(
            "video:event_room", args=[registration.event.slug]
        )
    with _recipient_timezone(registration.user):
        body = render_to_string(
            "payments/email/confirmation.txt",
            {
                "registration": registration,
                "is_comp": registration.status == Registration.Status.COMPED,
                "has_access": has_access,
                "room_url": room_url,
                "support_email": settings.SUPPORT_EMAIL,
                "site_base_url": settings.SITE_BASE_URL,
            },
        )
    _send(subject=subject, body=body, to=[registration.user.email])


def send_receipt(payment: Payment) -> None:
    """Send the receipt email (REG-7) and stamp ``emailed_at``."""
    receipt = payment.receipt
    subject = f"Receipt {receipt.receipt_number} — Lacanian School of Psychoanalysis"
    with _recipient_timezone(payment.user):
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
    _send(subject=subject, body=body, to=[to_email], sender="LSP Treasurer")
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
    """Weekly reminder email to an unpaid dues-obligated user (REG-12).

    Resolves the dues amount from the user's role via the period's tier
    mapping so the email shows the correct per-role amount.
    """
    subject = f"Reminder: {period.name} dues are due"
    amount = period.amount_for_role(user.profile.role)
    with _recipient_timezone(user):
        body = render_to_string(
            "payments/email/dues_reminder.txt",
            {
                "user": user,
                "period": period,
                "amount": amount,
                "support_email": settings.SUPPORT_EMAIL,
                "site_base_url": settings.SITE_BASE_URL,
            },
        )
    _send(subject=subject, body=body, to=[user.email], sender="LSP Treasurer")


def send_tuition_reminder(user, period, *, enrollment=None) -> None:
    """Reminder for an in-training student who hasn't decided / paid for the year (M7.5).

    Four phrasings depending on enrollment state:
    - no enrollment row: "please record your decision at /tuition/"
    - status=committed but unpaid: "please pay or set up a payment plan"
    - status=payment_plan with an installment due or overdue: names that
      installment, its amount, and its date (task #494 — nothing charges
      automatically, so this nudge is the only thing that moves a plan along)
    - anything else: the recorded decision, with a link to change it
    """
    from payments import plans

    subject = f"Tuition for {period.name}: please respond"
    installment = None
    installment_total = 0
    if enrollment is not None and (
        enrollment.status == enrollment.Status.PAYMENT_PLAN
    ):
        installment = plans.due_installment(enrollment, timezone.now().date())
        installment_total = enrollment.installments.count()
    with _recipient_timezone(user):
        body = render_to_string(
            "payments/email/tuition_reminder.txt",
            {
                "user": user,
                "period": period,
                "enrollment": enrollment,
                "installment": installment,
                "installment_total": installment_total,
                "installment_overdue": (
                    installment is not None
                    and installment.due_date < timezone.now().date()
                ),
                "support_email": settings.SUPPORT_EMAIL,
                "site_base_url": settings.SITE_BASE_URL,
            },
        )
    _send(subject=subject, body=body, to=[user.email], sender="LSP Treasurer")


def send_balance_reminder(user, balance) -> None:
    """Weekly reminder to a member with an outstanding unified-ledger balance
    (task #450 phase D).

    ``balance`` is the same number the treasurer's Accounts view shows as
    "Owing" — computed by ``payments.ledger`` (dues + tuition + registration
    fees, whichever is unpaid), never recomputed here.
    """
    subject = "Your Lacanian School account balance"
    account_url = settings.SITE_BASE_URL.rstrip("/") + reverse(
        "formation:formation") + "?tab=account"
    with _recipient_timezone(user):
        body = render_to_string(
            "payments/email/balance_reminder.txt",
            {
                "user": user,
                "balance": balance,
                "account_url": account_url,
                "support_email": settings.SUPPORT_EMAIL,
            },
        )
    _send(subject=subject, body=body, to=[user.email], sender="LSP Treasurer")


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
    with _recipient_timezone(registration.user):
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


# --- Faculty-approval flow ----------------------------------------------------

def _faculty_recipients(event) -> list[str]:
    """Emails of the event's faculty; falls back to support so nothing is lost."""
    emails = [u.email for u in event.faculty_members() if u.email]
    return emails or [settings.SUPPORT_EMAIL]


def _faculty_tools_url(event) -> str:
    """Absolute URL to where faculty approve registrations (the Workspace
    Roster tab for offerings, else the event's faculty view)."""
    if event.workgroup_id and event.event_type in event.ANNUAL_PROGRAM_TYPES:
        path = event.workgroup.get_absolute_url() + "?tab=roster"
    else:
        path = reverse("events:detail", args=[event.slug]) + "?view=faculty"
    return settings.SITE_BASE_URL + path


def _confirm_url(registration) -> str:
    return settings.SITE_BASE_URL + reverse(
        "registrations:confirm", args=[registration.id]
    )


def send_registration_pending_notice(registration: Registration) -> None:
    """Tell the event's faculty that someone registered and needs approval."""
    event = registration.event
    who = registration.user.get_full_name() or registration.user.email
    subject = f"Approval needed: {who} — {event.title}"
    body = render_to_string(
        "payments/email/registration_pending_faculty.txt",
        {
            "registration": registration,
            "event": event,
            "tools_url": _faculty_tools_url(event),
            "support_email": settings.SUPPORT_EMAIL,
        },
    )
    _send(subject=subject, body=body, to=_faculty_recipients(event))


def send_registration_approved(registration: Registration) -> None:
    """Tell the registrant their registration was approved and payment is due."""
    subject = f"Approved — complete your registration: {registration.event.title}"
    with _recipient_timezone(registration.user):
        body = render_to_string(
            "payments/email/registration_approved.txt",
            {
                "registration": registration,
                "confirm_url": _confirm_url(registration),
                "support_email": settings.SUPPORT_EMAIL,
            },
        )
    _send(subject=subject, body=body, to=[registration.user.email])


def send_registration_declined(registration: Registration) -> None:
    """Tell the registrant their registration was declined."""
    subject = f"Registration update: {registration.event.title}"
    with _recipient_timezone(registration.user):
        body = render_to_string(
            "payments/email/registration_declined.txt",
            {
                "registration": registration,
                "support_email": settings.SUPPORT_EMAIL,
            },
        )
    _send(subject=subject, body=body, to=[registration.user.email])


def send_approval_reminder(event, pending_count: int) -> None:
    """Remind the event's faculty that registrations await their approval."""
    subject = f"Reminder: {pending_count} registration(s) await your approval — {event.title}"
    body = render_to_string(
        "payments/email/approval_reminder.txt",
        {
            "event": event,
            "pending_count": pending_count,
            "tools_url": _faculty_tools_url(event),
            "support_email": settings.SUPPORT_EMAIL,
        },
    )
    _send(subject=subject, body=body, to=_faculty_recipients(event))


def send_payment_reminder(registration: Registration) -> None:
    """Remind an approved registrant to complete payment."""
    subject = f"Reminder: complete your registration — {registration.event.title}"
    with _recipient_timezone(registration.user):
        body = render_to_string(
            "payments/email/payment_reminder.txt",
            {
                "registration": registration,
                "confirm_url": _confirm_url(registration),
                "support_email": settings.SUPPORT_EMAIL,
            },
        )
    _send(subject=subject, body=body, to=[registration.user.email])


def send_installment_reminder(installment) -> None:
    """Nudge a registrant about the next payment on their plan (task #501)."""
    from . import registration_plans

    registration = installment.registration
    subject = (
        f"Reminder: payment {installment.sequence} for "
        f"{registration.event.title}"
    )
    with _recipient_timezone(registration.user):
        body = render_to_string(
            "payments/email/installment_reminder.txt",
            {
                "registration": registration,
                "installment": installment,
                "total": registration.installments.count(),
                "outstanding": registration_plans.outstanding(registration),
                "confirm_url": _confirm_url(registration),
                "support_email": settings.SUPPORT_EMAIL,
            },
        )
    _send(subject=subject, body=body, to=[registration.user.email])
