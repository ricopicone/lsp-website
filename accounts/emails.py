"""Outbound transactional email from the accounts app."""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.urls import reverse

# NB: the Find-an-Analyst referral emails moved to the ``referrals`` app
# (referrals.emails / referrals.services) when intake became a tracked
# ReferralRequest.


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


def send_magic_link(link, next_url: str = "") -> None:
    """Email a passwordless sign-in link to the account's address.

    ``link`` is a :class:`accounts.models.MagicLoginLink`. The link is
    single-use and short-lived (:attr:`MagicLoginLink.TOKEN_TTL`).
    ``next_url`` (a validated, site-relative path) is carried through so the
    user lands back where they were headed — e.g. a meeting deep link that
    bounced them through sign-in. It's a path, not a credential.
    """
    sign_in_url = settings.SITE_BASE_URL.rstrip("/") + reverse(
        "magic_link_consume", args=[link.token]
    )
    if next_url:
        from urllib.parse import urlencode

        sign_in_url += "?" + urlencode({"next": next_url})
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


def send_signup_verification(verification) -> None:
    """Email the confirm-your-address link for a new self-signup.

    The link lands on a page with a confirm button rather than activating on
    GET — mail scanners pre-click links, and this flow deliberately serves
    the kind of corporate/.gov addresses whose filters do so.
    """
    confirm_url = settings.SITE_BASE_URL.rstrip("/") + reverse(
        "signup_verify", args=[verification.token]
    )
    body = render_to_string(
        "accounts/email/signup_verification.txt",
        {
            "user": verification.user,
            "confirm_url": confirm_url,
            "ttl_days": verification.TOKEN_TTL.days,
        },
    )
    msg = EmailMessage(
        subject="Confirm your Lacanian School account",
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[verification.user.email],
        reply_to=[settings.SUPPORT_EMAIL],
    )
    msg.send(fail_silently=False)
