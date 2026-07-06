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


def _persona_owner_map() -> dict[str, str | None]:
    """``{persona_email_lower: owner_email_or_None}`` for every persona.

    A persona with an owner (a training-sandbox persona) has its mail
    *redirected* to the owner; an ownerless persona has its mail *dropped*.
    """
    from accounts.models import Profile

    return {
        email.lower(): (owner or None)
        for email, owner in Profile.objects.filter(is_persona=True).values_list(
            "user__email", "persona_owner__email"
        )
        if email
    }


class PersonaSafeEmailBackend(BaseEmailBackend):
    """Never delivers to persona addresses. Ownerless personas are dropped;
    sandbox personas (with an owner) are redirected to their owner, tagged
    ``[SANDBOX → <original recipients>]`` so a trainee sees exactly what each
    party in the workflow receives — without any of it reaching real members."""

    def __init__(self, fail_silently: bool = False, **kwargs):
        super().__init__(fail_silently=fail_silently)
        self._inner = get_connection(
            backend=getattr(settings, INNER_SETTING, DEFAULT_INNER),
            fail_silently=fail_silently,
        )

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        pmap = _persona_owner_map()
        if not pmap:
            return self._inner.send_messages(email_messages)

        kept = []
        for m in email_messages:
            redirected: set[str] = set()
            persona_targets: list[str] = []

            def _filter(addrs):
                real = []
                for a in addrs:
                    if a.lower() not in pmap:
                        real.append(a)  # a real recipient — keep
                        continue
                    persona_targets.append(a)
                    owner = pmap[a.lower()]
                    if owner:
                        redirected.add(owner)  # sandbox persona → owner
                    # ownerless persona → dropped
                return real

            m.to, m.cc, m.bcc = _filter(m.to), _filter(m.cc), _filter(m.bcc)
            if redirected:
                m.to = list(m.to) + [o for o in redirected if o not in m.to]
                tag = ", ".join(sorted(set(persona_targets)))
                m.subject = f"[SANDBOX → {tag}] {m.subject}"
            if m.to or m.cc or m.bcc:
                kept.append(m)
        return self._inner.send_messages(kept) if kept else 0
