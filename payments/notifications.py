"""Notification wrappers for the payments / registrations domain.

Each function raises an in-app notification (the nav bell) and, when the
member's preference allows, sends the matching email — the existing rich email
templates are passed to :func:`notifications.dispatch.notify` as ``email_fn``,
so wording and Reply-To behaviour are unchanged. Transactional categories
(confirmation, receipt) are email-locked, so their email always sends.

Call sites import these instead of calling ``payments.emails`` directly, which
keeps the in-app/email decision in one place.
"""

from __future__ import annotations

from django.urls import reverse

from notifications.categories import Category
from notifications.dispatch import notify
from notifications.preferences import resolve

from . import emails


def _confirm_url(reg) -> str:
    return reverse("registrations:confirm", args=[reg.id])


# --- Registrant-facing ------------------------------------------------------

def registration_confirmed(reg) -> None:
    """PAID/COMPED — confirmation + access. Email locked (always sends)."""
    notify(
        reg.user, Category.REGISTRATION_CONFIRMED,
        title=f"Registration confirmed: {reg.event.title}",
        url=_confirm_url(reg), target=reg,
        email_fn=lambda: emails.send_registration_confirmation(reg),
    )


def registration_approved(reg) -> None:
    notify(
        reg.user, Category.REGISTRATION_STATUS,
        title=f"Approved — complete your registration: {reg.event.title}",
        url=_confirm_url(reg), target=reg,
        email_fn=lambda: emails.send_registration_approved(reg),
    )


def registration_declined(reg) -> None:
    notify(
        reg.user, Category.REGISTRATION_STATUS,
        title=f"Registration update: {reg.event.title}",
        url=reverse("events:detail", args=[reg.event.slug]), target=reg,
        email_fn=lambda: emails.send_registration_declined(reg),
    )


def registration_cancelled(reg, *, refund=None) -> None:
    notify(
        reg.user, Category.REGISTRATION_STATUS,
        title=f"Registration cancelled: {reg.event.title}",
        url=reverse("events:detail", args=[reg.event.slug]), target=reg,
        email_fn=lambda: emails.send_cancellation_email(reg, refund=refund),
    )


def payment_reminder_inapp(reg) -> None:
    """Bell row for an approved-but-unpaid registrant (the cron paces the email
    itself, gated by :func:`should_email`)."""
    notify(
        reg.user, Category.REGISTRATION_STATUS,
        title=f"Reminder: complete your registration — {reg.event.title}",
        url=_confirm_url(reg), target=reg, email=False, dedupe=True,
    )


def payment_receipt(payment) -> None:
    """A receipt for a succeeded payment. Email locked (always sends)."""
    if not hasattr(payment, "receipt"):
        return
    receipt = payment.receipt
    url = reverse("payments:thanks", args=[payment.id])
    if payment.user_id:
        notify(
            payment.user, Category.PAYMENT_RECEIPT,
            title=f"Receipt {receipt.receipt_number}",
            url=url, target=payment,
            email_fn=lambda: emails.send_receipt(payment),
        )
    else:
        # Donation with no user account — email only, no bell row possible.
        emails.send_receipt(payment)


def should_email(user, category) -> bool:
    """Whether ``user`` wants email for ``category`` — for batch (throttled)
    senders that pace their own SMTP sends."""
    return resolve(user, category).email


def dues_reminder_inapp(user, period) -> None:
    """Raise the dues-reminder bell row only (the cron paces the email itself
    through ``ThrottledSender``, gated by :func:`should_email`)."""
    notify(
        user, Category.DUES_REMINDER,
        title=f"Reminder: {period.name} dues are due",
        url="/dues/", email=False, dedupe=True,
    )


def tuition_reminder_inapp(user, period) -> None:
    notify(
        user, Category.TUITION_REMINDER,
        title=f"Tuition for {period.name}: please respond",
        url="/tuition/", email=False, dedupe=True,
    )


# --- Faculty-facing ---------------------------------------------------------

def registration_pending(reg) -> None:
    """Tell event faculty a registration needs approval. The batched faculty
    email is unchanged; each faculty member also gets a bell row."""
    event = reg.event
    who = reg.user.get_full_name() or reg.user.email
    url = reverse("events:detail", args=[event.slug]) + "?view=faculty"
    for faculty in event.faculty_members():
        notify(
            faculty, Category.REGISTRATION_STATUS,
            title=f"Approval needed: {who} — {event.title}",
            url=url, target=reg, email=False, dedupe=True,
        )
    emails.send_registration_pending_notice(reg)


def _account_tab_url() -> str:
    from urllib.parse import urlencode

    from django.urls import reverse
    return reverse("formation:formation") + "?" + urlencode({"tab": "account"})


def ledger_submission_decided(submission) -> None:
    """Tell the member their history submission (task #439 §3) was decided.

    Filed under ``Category.ACCOUNT_UPDATES`` — this is an outcome on the
    member's own financial account, not a registration, so the old
    "Registration updates" preference label misdescribed it (task #443).
    """
    from .models import LedgerSubmission

    kind_label = "payment" if submission.kind == LedgerSubmission.Kind.PAYMENT else "charge"
    if submission.status == LedgerSubmission.Status.APPROVED:
        title = (f"Your reported {kind_label} of ${submission.amount} was "
                 "added to your account.")
    else:
        note = f": {submission.decision_note}" if submission.decision_note else "."
        title = (f"Your reported {kind_label} of ${submission.amount} was "
                 f"declined{note}")
    notify(
        submission.user, Category.ACCOUNT_UPDATES,
        title=title, url=_account_tab_url(), target=submission,
    )


def approval_reminder_inapp(event, pending_count: int) -> None:
    """Bell rows for event faculty (the cron paces the batched faculty email)."""
    url = reverse("events:detail", args=[event.slug]) + "?view=faculty"
    for faculty in event.faculty_members():
        notify(
            faculty, Category.REGISTRATION_STATUS,
            title=f"{pending_count} registration(s) await your approval — {event.title}",
            url=url, target=event, email=False, dedupe=True,
        )
