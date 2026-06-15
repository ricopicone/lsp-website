"""A persona-safe email backend.

Wraps the real email backend and never delivers to persona test accounts —
their addresses aren't real mailboxes, so sending would only bounce (and hurt
SES reputation). All outbound mail flows through here, so any flow that would
email a persona (e.g. the Web Coordinator testing a registration while
impersonating one) is silently dropped for those recipients.
"""

from __future__ import annotations

from email.utils import formataddr

from django.conf import settings
from django.core.mail import get_connection
from django.core.mail.backends.base import BaseEmailBackend


def school_from(name: str | None = None) -> str:
    """A friendly ``From`` — ``"<name> <no-reply@…>"`` — using the configured
    sending address. ``name`` defaults to the site-wide ``EMAIL_FROM_NAME``.

    Inboxes show the address's local part ("no-reply") as the sender unless a
    display name is attached. Use this when a kind of mail should present a more
    specific sender (e.g. "LSP Referral Coordinator") from the same verified
    address. Generic mail can just use ``settings.DEFAULT_FROM_EMAIL``, which is
    already wrapped with the school's name.
    """
    address = getattr(settings, "DEFAULT_FROM_ADDRESS", "") or settings.DEFAULT_FROM_EMAIL
    display = name or getattr(settings, "EMAIL_FROM_NAME", "") or ""
    return formataddr((display, address)) if display else address

INNER_SETTING = "PERSONA_SAFE_INNER_EMAIL_BACKEND"
DEFAULT_INNER = "django.core.mail.backends.console.EmailBackend"


def _persona_addresses() -> set[str]:
    from accounts.models import Profile

    return {
        e.lower()
        for e in Profile.objects.filter(is_persona=True).values_list(
            "user__email", flat=True
        )
        if e
    }


class PersonaSafeEmailBackend(BaseEmailBackend):
    def __init__(self, fail_silently: bool = False, **kwargs):
        super().__init__(fail_silently=fail_silently)
        self._inner = get_connection(
            backend=getattr(settings, INNER_SETTING, DEFAULT_INNER),
            fail_silently=fail_silently,
        )

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        personas = _persona_addresses()
        if not personas:
            return self._inner.send_messages(email_messages)
        kept = []
        for m in email_messages:
            m.to = [a for a in m.to if a.lower() not in personas]
            m.cc = [a for a in m.cc if a.lower() not in personas]
            m.bcc = [a for a in m.bcc if a.lower() not in personas]
            if m.to or m.cc or m.bcc:
                kept.append(m)
        return self._inner.send_messages(kept) if kept else 0
