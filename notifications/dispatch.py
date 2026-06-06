"""The single chokepoint for raising a notification.

Every feature that wants to tell a member something calls :func:`notify`.
``notify`` looks up the member's preference for the category, writes the
in-app bell row when the in-app channel is on, and sends an email when the
email channel is on — either a rich app-specific email (pass ``email_fn``) or
a generic one rendered from the title/body/url.

Email is dispatched on ``transaction.on_commit`` so a failed send never rolls
back the originating write, and a row that is rolled back never emails.

Parlêtre is a special case: it keeps its own per-channel email logic (reply-by-
email tokens, digests), so it passes ``email=False`` and ``notify`` only writes
the bell row.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from . import emails
from .models import Notification
from .preferences import resolve

log = logging.getLogger("notifications")


def notify(
    recipient,
    category: str,
    *,
    title: str,
    body: str = "",
    url: str = "",
    actor=None,
    target=None,
    email: str | bool = "auto",
    email_fn=None,
    dedupe: bool = False,
) -> Notification | None:
    """Raise a notification for ``recipient``.

    Returns the created :class:`Notification`, or ``None`` when neither channel
    fired (or it was de-duplicated).

    Parameters
    ----------
    email:
        ``"auto"`` (default) → the member's preference decides; ``False`` →
        suppress email here (the caller sends its own, as Parlêtre does).
    email_fn:
        Optional zero-arg callable that sends a rich, app-specific email. When
        email should go out and ``email_fn`` is given it is invoked on commit;
        otherwise a generic email is sent.
    dedupe:
        When true, skip creating a second *unread* in-app row with the same
        recipient + category + target (avoids repeat-reminder spam).
    """
    if recipient is None or not getattr(recipient, "pk", None):
        return None

    res = resolve(recipient, category)
    send_email = res.email if email != False else False  # noqa: E712 — explicit

    if not res.in_app and not send_email:
        return None

    notification = None
    if res.in_app:
        if dedupe and _has_unread_duplicate(recipient, category, target):
            notification = None
        else:
            notification = Notification(
                recipient=recipient,
                actor=actor if getattr(actor, "pk", None) else None,
                category=str(category),
                title=title[:255],
                body=(body or "")[:512],
                url=url or "",
            )
            if target is not None and getattr(target, "pk", None):
                notification.target = target
            if send_email:
                notification.emailed_at = timezone.now()
            notification.save()

    if send_email:
        _schedule_email(recipient, title, body, url, email_fn)

    return notification


def _has_unread_duplicate(recipient, category, target) -> bool:
    qs = Notification.objects.filter(
        recipient=recipient, category=str(category), read_at__isnull=True
    )
    if target is not None and getattr(target, "pk", None):
        from django.contrib.contenttypes.models import ContentType

        qs = qs.filter(
            target_type=ContentType.objects.get_for_model(target),
            target_id=target.pk,
        )
    return qs.exists()


def _schedule_email(recipient, title, body, url, email_fn) -> None:
    def _send():
        try:
            if email_fn is not None:
                email_fn()
            else:
                emails.send_generic(recipient, title, body, url)
        except Exception:  # an email failure must never break the request
            log.exception("notifications: email send failed for %s", recipient)

    transaction.on_commit(_send)
