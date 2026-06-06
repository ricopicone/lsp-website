"""The generic notification email — used when a category has no richer,
app-specific email template of its own. Rich emails (receipts, registration
confirmations, cartel invitations, …) keep their existing templates and are
invoked through ``notify(email_fn=...)``; this is the plain fallback.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

log = logging.getLogger("notifications")


def _abs(path: str) -> str:
    if not path:
        return settings.SITE_BASE_URL.rstrip("/")
    if path.startswith("http"):
        return path
    return f"{settings.SITE_BASE_URL.rstrip('/')}{path}"


def send_generic(recipient, title: str, body: str = "", url: str = "") -> None:
    """Email ``recipient`` a plain notification."""
    if not getattr(recipient, "email", ""):
        return
    context = {
        "recipient": recipient,
        "title": title,
        "body": body,
        "url": _abs(url),
        "settings_url": _abs("/notifications/settings/"),
    }
    message = render_to_string("notifications/email/generic.txt", context)
    email = EmailMessage(
        subject=title,
        body=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient.email],
        reply_to=[settings.SUPPORT_EMAIL],
    )
    try:
        email.send(fail_silently=False)
    except Exception:
        log.exception("notifications: failed to send generic email to %s", recipient.email)
