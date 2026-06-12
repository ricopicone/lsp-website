"""Outbound email for the referral workflow.

Requester-facing messages get their subject and body from the editable
:class:`referrals.models.MessageTemplate` rows (rendered in ``services``),
so this module only addresses and sends. All mail goes out from
``DEFAULT_FROM_EMAIL`` with Reply-To at the referrals mailbox, so a reply
from anyone lands with the coordinator.
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.template.loader import render_to_string


def referrals_address() -> str:
    return getattr(settings, "REFERRALS_EMAIL", "referrals@lacanschool.org")


def send_coordinator_inquiry(request_obj, manage_url: str) -> None:
    """Email a new submission to the referrals mailbox (steps 1–2).

    Reply-To is the requester, so the coordinator can still hit Reply in her
    mail client to reach them directly — the manual escape hatch.
    """
    context = {"req": request_obj, "manage_url": manage_url}
    text_body = render_to_string("referrals/email/inquiry.txt", context)
    html_body = render_to_string("referrals/email/inquiry.html", context)
    msg = EmailMultiAlternatives(
        subject=(
            f"Find-an-Analyst inquiry {request_obj.reference} — "
            f"{request_obj.name}"
        ),
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[referrals_address()],
        reply_to=[request_obj.email],
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)


def send_to_requester(request_obj, subject: str, body: str) -> None:
    """A rendered template (acknowledgment or follow-up) to the requester."""
    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[request_obj.email],
        reply_to=[referrals_address()],
    )
    msg.send(fail_silently=False)


def send_to_clinician(user, subject: str, body: str) -> None:
    """A rendered template (distribution or onboarding) to a list member."""
    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
        reply_to=[referrals_address()],
    )
    msg.send(fail_silently=False)
