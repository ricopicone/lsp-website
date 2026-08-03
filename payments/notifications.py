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


def installment_reminder_inapp(installment) -> None:
    """Bell row for a due payment-plan installment (task #501). The cron paces
    the email itself, gated by :func:`should_email`."""
    reg = installment.registration
    notify(
        reg.user, Category.REGISTRATION_STATUS,
        title=(
            f"Payment {installment.sequence} of your plan for "
            f"{reg.event.title} is due"
        ),
        url=_confirm_url(reg), target=installment, email=False, dedupe=True,
    )


def plan_cancel_needs_treasurer(registration) -> None:
    """Tell the treasurer a payment-plan registrant asked to cancel (task
    #501). The site deliberately refuses to decide the refund — a member who
    attended part of an event is a pro-rating conversation, not a full
    refund."""
    from core.models import StaffRole

    role = StaffRole.objects.filter(key=StaffRole.TREASURER).first()
    holders = list(role.holders.all()) if role else []
    if not holders:
        log.warning(
            "plan_cancel_needs_treasurer: no Treasurer role holder — "
            "registration %s cancellation request unseen", registration.pk,
        )
        return
    who = registration.user.get_full_name() or registration.user.email
    for user in holders:
        notify(
            user, Category.ACCOUNT_UPDATES,
            title=f"Cancellation request on a payment plan: {who}",
            body=(
                f"{who} asked to cancel their registration for "
                f'"{registration.event.title}" (${registration.quoted_amount} '
                "on a payment plan). The refund needs your decision."
            ),
            url=reverse("treasurer_member_detail", args=[registration.user_id]),
            target=registration, dedupe=True,
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
    application (task #450 phase B).

    Its own category, separate from the reviewers' queue (task #491): the
    queue's email now defaults to the Treasurer alone, and that must never
    silence an applicant hearing their own outcome.
    """
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
        # A pending request carried event coverage (task #484). Say what each
        # branch of the choice now costs (task #485).
        body = (
            "Your tuition decision is open again on your Account tab. If you "
            "record that you plan to pay tuition, any events you registered "
            "for stay covered. If you skip this year, those events carry their "
            "regular fee and you'll be shown the total before it applies."
        )
    notify(
        application.user, Category.TUITION_PLAN_DECISION,
        title=title, body=body, url=_account_tab_url(), target=application,
    )


def notify_coverage_rebilled(user, period, registrations) -> None:
    """Tell the member the events tuition had covered now carry their regular
    fee, because they recorded skipping for the year (task #485)."""
    total = sum(r.quoted_amount for r in registrations)
    count = len(registrations)
    plural = "registration" if count == 1 else "registrations"
    notify(
        user, Category.ACCOUNT_UPDATES,
        title=(
            f"{count} {plural} now carries the regular fee, ${total} in total, "
            f"because you're skipping tuition for {period.name}."
        ),
        body=(
            "You can pay each fee from its registration page. If you decide to "
            f"pay tuition for {period.name} after all, record that on your "
            "Account tab and these events go back to being covered, at no cost."
        ),
        url=_account_tab_url(),
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
