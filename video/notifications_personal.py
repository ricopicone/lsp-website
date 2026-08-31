"""Telling someone they've been invited into a private meeting room (task #687).

Two audiences with two mechanisms, because they are two different people:

* an **account holder** gets a bell row and (by preference) an email, through
  the ordinary ``notify`` chokepoint;
* a **guest** has no account and so no preferences, and is emailed directly —
  only when the member supplied an address. The secret link is always shown to
  the member as well, since handing it over in person or in an existing email
  thread is often what they want.
"""
from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.urls import reverse

from core.email import school_from
from notifications.categories import Category
from notifications.dispatch import notify


def _absolute(path: str) -> str:
    return settings.SITE_BASE_URL.rstrip("/") + path


def invitation_url(invitation) -> str:
    if invitation.is_guest:
        return _absolute(reverse("video:guest_room", args=[invitation.token]))
    return _absolute(reverse("video:personal_room", args=[invitation.personal_room.slug]))


def _host_name(room) -> str:
    return room.user.get_full_name() or room.user.email


def invited_user(invitation) -> None:
    """Bell + email for someone who has an account."""
    room = invitation.personal_room
    host = _host_name(room)
    notify(
        invitation.invited_user,
        Category.MEETING_ROOM_INVITE,
        title=f"{host} invited you to their private meeting room",
        body=(invitation.note or "").strip(),
        url=reverse("video:personal_room", args=[room.slug]),
        actor=room.user,
        target=invitation,
    )


def invited_guest(invitation) -> None:
    """Email a guest their secret link, when the member gave us an address."""
    if not invitation.guest_email:
        return
    room = invitation.personal_room
    context = {
        "host": _host_name(room),
        "guest_name": invitation.guest_name,
        "note": (invitation.note or "").strip(),
        "join_url": invitation_url(invitation),
        "expires_at": invitation.expires_at,
    }
    body = render_to_string("video/email/guest_invitation.txt", context)
    EmailMessage(
        subject=f"{context['host']} invited you to a meeting",
        body=body,
        from_email=school_from(),
        to=[invitation.guest_email],
        reply_to=[room.user.email],
    ).send(fail_silently=True)


def send_invitation(invitation) -> None:
    """Whichever of the two applies."""
    if invitation.is_guest:
        invited_guest(invitation)
    else:
        invited_user(invitation)
