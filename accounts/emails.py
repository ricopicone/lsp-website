"""Outbound transactional email from the accounts app."""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage, EmailMultiAlternatives
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


def _send_with_html(subject: str, to: str, txt_template: str, context: dict) -> None:
    """Send text + house-styled HTML (task #450): the plain body renders from
    ``txt_template`` and the HTML alternative from its ``.html`` sibling
    (``…/foo.txt`` -> ``…/foo.html``), both from the same context."""
    msg = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string(txt_template, context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to],
        reply_to=[settings.SUPPORT_EMAIL],
    )
    msg.attach_alternative(
        render_to_string(txt_template[:-4] + ".html", context), "text/html"
    )
    msg.send(fail_silently=False)


def send_welcome(user) -> None:
    """The one-time launch welcome: the site is live, here's how to sign in.

    Sent by ``manage.py send_welcome_emails``, which records a
    :class:`accounts.models.WelcomeEmail` per delivery so nobody is
    welcomed twice.
    """
    base = settings.SITE_BASE_URL.rstrip("/")
    _send_with_html(
        "Welcome to the LSP Website",
        user.email,
        "accounts/email/welcome.txt",
        {
            "user": user,
            "login_url": base + reverse("login"),
            "guide_url": base + reverse("guide_detail", args=["logging-in"]),
            "guides_url": base + reverse("guides_index"),
        },
    )


def send_account_ready(user, *, track) -> None:
    """Tell a directly-admitted member their account exists and how to get in.

    Sent by the Web Coordinator's direct-admission form to someone who was
    already welcomed to the school off-site, so it opens the account rather
    than announcing the decision (the full acceptance letter is
    ``admissions.emails.send_direct_acceptance``). The set-password link is
    Django's own password-reset token, so there's no second expiry mechanism
    to maintain; a lapsed link falls back to the magic sign-in link.
    """
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    from admissions.emails import _guidelines_url

    base = settings.SITE_BASE_URL.rstrip("/")
    set_password_url = base + reverse(
        "password_reset_confirm",
        kwargs={
            "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": default_token_generator.make_token(user),
        },
    )
    _send_with_html(
        "Your LSP member account is ready",
        user.email,
        "accounts/email/account_ready.txt",
        {
            "user": user,
            "set_password_url": set_password_url,
            "ttl_days": settings.PASSWORD_RESET_TIMEOUT // 86400,
            "login_url": base + reverse("login"),
            "availability_url": base + reverse("directory_availability") + "?only=advisor",
            "guidelines_url": _guidelines_url(track),
            "documents_url": base + reverse("documents:index"),
            "profile_url": base + reverse("profile_edit"),
            "mylsp_url": base + reverse("formation:formation"),
        },
    )


# --- Batch announcements -------------------------------------------------
#
# Keyed campaigns sent by ``manage.py send_announcement_emails --key <key>``;
# an ``AnnouncementEmail`` row per (user, key) makes re-runs safe. Add a key
# here (subject, template, extra context) to mint a new announcement — e.g.
# next year's program opening.

ANNOUNCEMENTS: dict[str, dict] = {
    "site-launch-2026": {
        "subject": "The Lacanian School's New Website",
        "template": "accounts/email/announcement_site_launch.txt",
        "context": {},
    },
    "program-2026-2027": {
        "subject": "The 2026\u20132027 Program Is Open for Registration",
        "template": "accounts/email/announcement_program_open.txt",
        "context": {"academic_year": "2026\u20132027"},
    },
}


def send_announcement(user, key: str) -> None:
    """Send one keyed announcement email (see ``ANNOUNCEMENTS``)."""
    spec = ANNOUNCEMENTS[key]
    base = settings.SITE_BASE_URL.rstrip("/")
    context = {
        "user": user,
        "site_url": base + "/",
        "program_url": base + reverse("program"),
        "seminars_guide_url": base + reverse("guide_detail", args=["seminars"]),
        **spec["context"],
    }
    _send_with_html(spec["subject"], user.email, spec["template"], context)


def send_signup_verification(verification) -> None:
    """Email the confirm-your-address link for a new self-signup (task #471).

    The link lands on a page with a confirm button rather than activating on
    GET — mail scanners pre-click links, and this flow deliberately serves
    the kind of corporate/.gov addresses whose filters do so.
    """
    confirm_url = settings.SITE_BASE_URL.rstrip("/") + reverse(
        "signup_verify", args=[verification.token]
    )
    _send_with_html(
        "Confirm your Lacanian School account",
        verification.user.email,
        "accounts/email/signup_verification.txt",
        {
            "user": verification.user,
            "confirm_url": confirm_url,
            "ttl_days": verification.TOKEN_TTL.days,
        },
    )
