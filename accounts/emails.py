"""Outbound transactional email from the accounts app."""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string


def send_referral_inquiry(form_cleaned: dict) -> None:
    """Email a Find-an-Analyst form submission to the referral coordinator.

    From: ``DEFAULT_FROM_EMAIL`` (stable sending domain for SES/DKIM).
    Reply-To: the inquirer's email — so the coordinator's reply reaches
    the person who submitted the form, not the no-reply mailbox.
    """
    to = [getattr(settings, "REFERRALS_EMAIL", "referrals@lacanschool.org")]
    subject = f"Find-an-Analyst inquiry — {form_cleaned['name']}"
    body = render_to_string(
        "accounts/email/referral_inquiry.txt",
        {"data": form_cleaned},
    )
    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=to,
        reply_to=[form_cleaned["email"]],
    )
    msg.send(fail_silently=False)
