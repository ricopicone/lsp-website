"""Outbound transactional email from the accounts app."""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse


def send_referral_inquiry(form_cleaned: dict) -> None:
    """Email a Find-an-Analyst form submission to the referral coordinator.

    From: ``DEFAULT_FROM_EMAIL`` (stable sending domain for SES/DKIM).
    Reply-To: the inquirer's email — so the coordinator's reply reaches
    the person who submitted the form, not the no-reply mailbox.
    """
    to = [getattr(settings, "REFERRALS_EMAIL", "referrals@lacanschool.org")]
    subject = f"Find-an-Analyst inquiry — {form_cleaned['name']}"
    context = {"data": form_cleaned}
    text_body = render_to_string("accounts/email/referral_inquiry.txt", context)
    html_body = render_to_string("accounts/email/referral_inquiry.html", context)
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=to,
        reply_to=[form_cleaned["email"]],
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)


def send_referral_acknowledgment(form_cleaned: dict) -> None:
    """Email an acknowledgment to the person who submitted the referral form.

    Reply-To points at the referrals mailbox so any follow-up from the
    inquirer reaches the coordinator directly.
    """
    referrals = getattr(settings, "REFERRALS_EMAIL", "referrals@lacanschool.org")
    subject = "Thank you for contacting the Lacanian School"
    body = render_to_string(
        "accounts/email/referral_acknowledgment.txt",
        {"data": form_cleaned, "referrals_email": referrals},
    )
    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[form_cleaned["email"]],
        reply_to=[referrals],
    )
    msg.send(fail_silently=False)


def send_email_change_verification(change_request) -> None:
    """Email a verification link to the *new* address of an email change.

    Clicking the link confirms control of the new address and switches the
    login email (see ``accounts.views.email_change_confirm``).
    """
    confirm_url = settings.SITE_BASE_URL.rstrip("/") + reverse(
        "email_change_confirm", args=[change_request.token]
    )
    body = render_to_string(
        "accounts/email/email_change_verification.txt",
        {
            "user": change_request.user,
            "new_email": change_request.new_email,
            "confirm_url": confirm_url,
            "ttl_hours": int(change_request.TOKEN_TTL.total_seconds() // 3600),
        },
    )
    msg = EmailMessage(
        subject="Confirm your new Lacanian School login email",
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[change_request.new_email],
        reply_to=[settings.SUPPORT_EMAIL],
    )
    msg.send(fail_silently=False)


def send_magic_link(link) -> None:
    """Email a passwordless sign-in link to the account's address.

    ``link`` is a :class:`accounts.models.MagicLoginLink`. The link is
    single-use and short-lived (:attr:`MagicLoginLink.TOKEN_TTL`).
    """
    sign_in_url = settings.SITE_BASE_URL.rstrip("/") + reverse(
        "magic_link_consume", args=[link.token]
    )
    body = render_to_string(
        "accounts/email/magic_link.txt",
        {
            "user": link.user,
            "sign_in_url": sign_in_url,
            "ttl_minutes": int(link.TOKEN_TTL.total_seconds() // 60),
            "support_email": settings.SUPPORT_EMAIL,
        },
    )
    msg = EmailMessage(
        subject="Your Lacanian School sign-in link",
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[link.user.email],
        reply_to=[settings.SUPPORT_EMAIL],
    )
    msg.send(fail_silently=False)


def send_email_change_notice(user, old_email: str, new_email: str) -> None:
    """Notify the *old* address that the account's login email was changed.

    A safety net: if the change wasn't authorized, the old-address owner
    learns about it and can contact support.
    """
    body = render_to_string(
        "accounts/email/email_change_notice.txt",
        {
            "user": user,
            "old_email": old_email,
            "new_email": new_email,
            "support_email": settings.SUPPORT_EMAIL,
        },
    )
    msg = EmailMessage(
        subject="Your Lacanian School login email was changed",
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[old_email],
        reply_to=[settings.SUPPORT_EMAIL],
    )
    msg.send(fail_silently=False)
