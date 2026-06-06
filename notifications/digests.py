"""Build and send the periodic notification digest.

A member can route any non-locked category to *In a digest* on the settings
page. Those notifications still appear in the bell immediately but their email
is held; this rolls every held item since the last digest into one email at the
member's chosen cadence (daily / weekly).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

from .categories import DigestCadence, meta_for
from .models import Notification

log = logging.getLogger("notifications")

_INTERVAL = {
    DigestCadence.DAILY: timedelta(days=1),
    DigestCadence.WEEKLY: timedelta(days=7),
}


def is_due(pref, now) -> bool:
    interval = _INTERVAL.get(pref.digest_cadence)
    if interval is None:  # OFF
        return False
    if pref.last_digest_at is None:
        return True
    return now - pref.last_digest_at >= interval


def pending_for(user) -> list[Notification]:
    return list(
        Notification.objects.filter(recipient=user, digest_pending=True)
        .order_by("created_at")
    )


def _sections(items):
    """Group items by their category section, preserving first-seen order."""
    grouped: dict[str, list] = {}
    for item in items:
        section = str(meta_for(item.category).section)
        grouped.setdefault(section, []).append(item)
    return [{"title": title, "items": rows} for title, rows in grouped.items()]


def _abs(path: str) -> str:
    if not path:
        return settings.SITE_BASE_URL.rstrip("/")
    if path.startswith("http"):
        return path
    return f"{settings.SITE_BASE_URL.rstrip('/')}{path}"


def render_digest(user, items) -> tuple[str, str]:
    """Return (subject, body) for ``user``'s digest of ``items``."""
    count = len(items)
    for item in items:
        item.abs_url = _abs(item.url)
    subject = f"Your LSP notifications ({count})"
    body = render_to_string(
        "notifications/email/digest.txt",
        {
            "recipient": user,
            "sections": _sections(items),
            "count": count,
            "settings_url": _abs("/notifications/settings/"),
            "feed_url": _abs("/notifications/"),
        },
    )
    return subject, body


def send_digest(user, items) -> bool:
    """Email ``user`` a digest of ``items``. Returns True if sent."""
    if not items or not getattr(user, "email", ""):
        return False
    subject, body = render_digest(user, items)
    EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
        reply_to=[settings.SUPPORT_EMAIL],
    ).send(fail_silently=False)
    return True


def clear_pending(items, now) -> None:
    ids = [n.pk for n in items]
    Notification.objects.filter(pk__in=ids).update(
        digest_pending=False, emailed_at=now
    )
