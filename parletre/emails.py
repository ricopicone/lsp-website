"""Outbound email for Parlêtre — immediate post notifications and digests.

Immediate emails go to members whose channel subscription is "loud" (every
post / new threads / on mention). Quiet (digest-level) subscriptions are
batched by the ``send_discussion_digests`` command instead. When reply-by-
email is enabled, notification emails carry a signed Reply-To so a reply
posts back to the thread (see :mod:`parletre.tokens`); digests don't (a
digest spans many threads, so there's nothing single to reply to).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

from . import tokens

log = logging.getLogger("parletre")

_VERB = {
    "mention": "mentioned you",
    "post": "posted",
    "new_thread": "started a thread",
    "reply": "replied",
}


def _reply_to(kind: str, target_id: int, recipient) -> list[str]:
    """A token Reply-To when reply-by-email is on, else the support address."""
    if getattr(settings, "PARLETRE_REPLY_ENABLED", False):
        token = tokens.make_token(kind, target_id, recipient.id)
        return [f"reply+{token}@{settings.PARLETRE_REPLY_DOMAIN}"]
    return [settings.SUPPORT_EMAIL]


def _abs(path: str) -> str:
    return f"{settings.SITE_BASE_URL.rstrip('/')}{path}"


def send_post_notification(post, recipient, reason: str) -> None:
    """Email ``recipient`` about ``post``. ``reason`` ∈ mention/post/new_thread/reply."""
    if not recipient.email:
        return
    channel = post.channel
    thread = post.thread
    if thread is not None:
        kind, target_id = tokens.THREAD, thread.id
        url = _abs(f"{thread.get_absolute_url()}#post-{post.id}")
        context_label = thread.title
    else:
        kind, target_id = tokens.CHANNEL, channel.id
        url = _abs(channel.get_absolute_url())
        context_label = f"#{channel.slug}"

    actor = post.author.get_full_name() if post.author else "Someone"
    verb = _VERB.get(reason, "posted")
    reply_enabled = getattr(settings, "PARLETRE_REPLY_ENABLED", False)
    body = render_to_string(
        "parletre/email/post_notification.txt",
        {
            "actor": actor or "Someone",
            "verb": verb,
            "channel": channel,
            "context_label": context_label,
            "post": post,
            "url": url,
            "reply_enabled": reply_enabled,
        },
    )
    subject = f"[Parlêtre] {actor or 'Someone'} {verb} — {context_label}"
    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient.email],
        reply_to=_reply_to(kind, target_id, recipient),
    )
    try:
        msg.send(fail_silently=False)
    except Exception:  # never let an email failure break the request
        log.exception("parletre: failed to send %s email to %s", reason, recipient.email)


def send_digest(user, sections, *, period_label: str) -> bool:
    """Send ``user`` a digest. ``sections`` is a list of
    ``{"channel", "threads": [{"thread", "posts": [...]}]}``. Returns True if sent."""
    if not user.email or not sections:
        return False
    body = render_to_string(
        "parletre/email/digest.txt",
        {
            "user": user,
            "sections": sections,
            "period_label": period_label,
            "base_url": settings.SITE_BASE_URL.rstrip("/"),
        },
    )
    msg = EmailMessage(
        subject=f"[Parlêtre] {period_label} digest",
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
        reply_to=[settings.SUPPORT_EMAIL],
    )
    try:
        msg.send(fail_silently=False)
        return True
    except Exception:
        log.exception("parletre: failed to send digest to %s", user.email)
        return False
