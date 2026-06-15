"""Outbound email for workgroups — currently the pre-meeting reminder.

The reminder carries two links: the plain Meet-tab URL (works for anyone
already signed in) and a *personal* magic link that signs the member in and
drops them on the Meet tab. The magic link is minted per recipient, valid only
for the meeting's window (capped at 9h), and labelled "don't share."
"""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import linebreaks, urlize


def _absolute(path: str) -> str:
    return settings.SITE_BASE_URL.rstrip("/") + path


def meet_tab_url(workgroup) -> str:
    """The plain (login-gated) Meet-tab URL for a workgroup."""
    return _absolute(f"{workgroup.get_absolute_url()}?tab=meet")


def meeting_window_expiry(meeting, now):
    """When a reminder's magic link should stop working: the meeting's end if
    known, else two hours after it starts — capped so it never outlives the
    meeting by much (the model clamps to MAX_TTL as a backstop)."""
    start = meeting.starts_at
    end = meeting.ends_at or (start + timedelta(hours=2))
    return end


def _personal_join_url(user, meeting, now):
    """A per-user magic link that signs in and lands on the Meet tab, valid for
    the meeting window only."""
    from accounts.models import MagicLoginLink

    link = MagicLoginLink.create_for_window(
        user, expires_at=meeting_window_expiry(meeting, now),
    )
    consume = reverse("magic_link_consume", args=[link.token])
    nxt = f"{meeting.workgroup.get_absolute_url()}?tab=meet"
    return _absolute(consume) + "?" + urlencode({"next": nxt})


def send_meeting_reminder(user, meeting) -> None:
    """Email ``user`` the pre-meeting reminder with both links. Mints the
    personal magic link as a side effect, so call it only when actually sending
    (the notifications layer invokes it via ``email_fn`` on commit)."""
    from django.utils import timezone

    now = timezone.now()
    wg = meeting.workgroup
    context = {
        "user": user,
        "meeting": meeting,
        "workgroup": wg,
        "starts_at": meeting.starts_at,
        "meet_url": meet_tab_url(wg),
        "personal_url": _personal_join_url(user, meeting, now),
        "support_email": settings.SUPPORT_EMAIL,
    }
    text_body = render_to_string("workgroups/email/meeting_reminder.txt", context)
    title = meeting.title or wg.name
    msg = EmailMultiAlternatives(
        subject=f"Starting soon: {title}",
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
        reply_to=[settings.SUPPORT_EMAIL],
    )
    # Simple HTML alternative: paragraphs kept, the plain links made clickable.
    html_body = (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,'
        "'Segoe UI',Roboto,Helvetica,Arial,sans-serif; font-size:15px; "
        'line-height:1.6; color:#18181b;">'
        + linebreaks(urlize(text_body, autoescape=True))
        + "</div>"
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)
