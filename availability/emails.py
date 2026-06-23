"""Outbound mail for the analyst-availability console.

One message today: the Applications Coordinator's reminder asking an analyst
to review which LSP functions they're available for. The link is a plain
login-gated deep link to the Availability section of the profile editor
(``?next=`` carries them there after sign-in) rather than a magic link —
reminders are opened over days, well past a magic link's short, capped TTL.
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.defaultfilters import linebreaks, urlize
from django.urls import reverse

from core.email import school_from

from . import services
from .models import ReminderTemplate

_FROM_NAME = "LSP Applications Coordinator"


def _absolute(path: str) -> str:
    return settings.SITE_BASE_URL.rstrip("/") + path


def update_url() -> str:
    """Absolute URL to the Availability section of the profile editor.

    Login-gated: an anonymous click lands on the sign-in page and returns here
    afterward via ``?next=``.
    """
    target = reverse("profile_edit") + "#availability"
    login = reverse("login")
    return _absolute(login) + "?" + urlencode({"next": target})


def _html_alternative(body: str) -> str:
    """Plain text as simple HTML: paragraphs kept, URLs linked."""
    return (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,'
        "'Segoe UI',Roboto,Helvetica,Arial,sans-serif; font-size:15px; "
        'line-height:1.6; color:#18181b;">'
        + linebreaks(urlize(body, autoescape=True))
        + "</div>"
    )


def applications_coordinator_name() -> str:
    """The appointed Applications Coordinator's name, for the {applications_
    coordinator} token. Joins multiple holders; falls back to a generic title
    when the role is unfilled."""
    from core.models import StaffRole

    role = StaffRole.objects.filter(
        key=StaffRole.APPLICATIONS_COORDINATOR
    ).prefetch_related("holders").first()
    if role:
        names = [
            h.get_full_name() or h.email
            for h in role.holders.all()
            if h.is_active
        ]
        if names:
            return ", ".join(names)
    return "the LSP Applications Coordinator"


def render_review_request(user) -> tuple[str, str]:
    """The (subject, body) of the review-request email for ``user``."""
    template = ReminderTemplate.get(ReminderTemplate.Key.REVIEW_REQUEST)
    context = {
        "name": user.get_full_name() or user.email,
        "update_url": update_url(),
        "applications_coordinator": applications_coordinator_name(),
    }
    return (
        services.render_template(template.subject, context),
        services.render_template(template.body, context),
    )


def send_review_request(user, subject: str, body: str) -> None:
    """Send the rendered review-request to one analyst."""
    msg = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=school_from(_FROM_NAME),
        to=[user.email],
        reply_to=[settings.APPLICATIONS_EMAIL],
    )
    msg.attach_alternative(_html_alternative(body), "text/html")
    msg.send(fail_silently=False)
