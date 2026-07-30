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

import logging

from django.urls import reverse

from notifications.categories import Category
from notifications.dispatch import notify
from notifications.preferences import resolve

from . import emails

log = logging.getLogger("notifications")


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


def _receipt_url(payment) -> str:
    """Where a receipt's bell row lands — the same split Stripe's success paths
    use. ``payments:thanks`` is a public page and so deliberately 404s
    registration payments; those belong on the registration confirmation page.
    """
    if payment.registration_id:
        return reverse("registrations:confirm", args=[payment.registration_id])
    return reverse("payments:thanks", args=[payment.id])


def payment_receipt(payment) -> None:
    """A receipt for a succeeded payment. Email locked (always sends)."""
    if not hasattr(payment, "receipt"):
        return
    receipt = payment.receipt
    url = _receipt_url(payment)
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


def balance_reminder_inapp(user, balance) -> None:
    """Bell row for an outstanding-balance reminder (the cron paces the
    email itself through ``ThrottledSender``, gated by :func:`should_email`)."""
    notify(
        user, Category.BALANCE_REMINDER,
        title=f"Reminder: ${balance} outstanding on your account",
        url=_account_tab_url(), email=False, dedupe=True,
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


def notify_plan_application_submitted(application) -> None:
    """Tell the Board a tuition payment-plan application awaits review
    (task #450 phase B)."""
    from committees.models import Committee

    board = Committee.objects.filter(slug="board").first()
    if board is None:
        log.warning(
            "notify_plan_application_submitted: no Board committee (slug="
            "'board') found — application %s submitted with no reviewers "
            "notified", application.pk,
        )
        return
    who = application.user.get_full_name() or application.user.email
    period = application.tuition_period
    url = "/admin-tools/tuition-plans/"
    body = f"{who} applied for a tuition payment plan for {period.name}."
    for membership in board.active_members().select_related("user"):
        if membership.user_id == application.user_id:
            continue
        notify(
            membership.user, Category.TUITION_PLAN_REVIEW,
            title=f"Payment plan request: {who} — {period.name}",
            body=body, url=url, target=application, dedupe=True,
        )


def notify_plan_application_decided(application) -> None:
    """Tell the applicant the Board's decision on their payment-plan
    application (task #450 phase B)."""
    from .models import TuitionPlanApplication

    period = application.tuition_period
    body = ""
    if application.status == TuitionPlanApplication.Status.APPROVED:
        title = f"The Board approved your payment plan application for {period.name}."
    else:
        title = (
            "The Board was unable to approve your payment plan application "
            f"for {period.name}. Please choose to pay in full or skip this "
            "year on your Account tab."
        )
        # A pending request carried event coverage (task #484), so a decline
        # can leave a $0 registration behind. Nothing unwinds automatically —
        # staff settle it, and the member should not be surprised.
        body = (
            "If you registered for an event with tuition coverage while your "
            "application was pending, we'll be in touch about settling it."
        )
    notify(
        application.user, Category.TUITION_PLAN_REVIEW,
        title=title, body=body, url=_account_tab_url(), target=application,
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
