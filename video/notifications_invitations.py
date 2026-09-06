"""Telling someone they have been invited into a meeting room (tasks #687, #694).

Two audiences with two mechanisms, because they are two different people:

* an **account holder** gets a bell row and (by preference) an email, through the
  ordinary ``notify`` chokepoint;
* a **guest** has no account and so no preferences, and is emailed directly, only
  when an address was given. The secret link is always shown to the person who
  issued it as well, since handing it over in person or in an existing email
  thread is often what they want.

The wording is the one thing that varies by target: a personal room is somebody's
own, so the message names the host, while a group's names the group and, when we
know it, the lead who opened the door.
"""
from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.urls import reverse

from core.email import school_from
from notifications.categories import Category
from notifications.dispatch import notify

from . import invitations as inv


def _absolute(path: str) -> str:
    return settings.SITE_BASE_URL.rstrip("/") + path


def invitation_url(invitation) -> str:
    """Where the invited person goes: the secret URL for a guest, and for an
    account holder the room's own URL, which they reach by signing in."""
    if invitation.is_guest:
        return _absolute(reverse("video:guest_room", args=[invitation.token]))
    return _absolute(inv.target_of(invitation).room_url())


def _inviter(invitation):
    """Who opened the door. A personal room's owner is implied by the room; a
    group records it on the row, since a group has several leads."""
    if invitation.invited_by_id:
        return invitation.invited_by
    room = invitation.personal_room
    return room.user if room is not None else None


def _inviter_name(invitation) -> str:
    person = _inviter(invitation)
    if person is None:
        return "The Lacanian School of Psychoanalysis"
    return person.get_full_name() or person.email


def _reply_to(invitation) -> list:
    person = _inviter(invitation)
    return [person.email if person is not None else settings.SUPPORT_EMAIL]


def invited_user(invitation) -> None:
    """Bell + preference-gated email for someone who has an account."""
    target = inv.target_of(invitation)
    inviter = _inviter_name(invitation)
    if target.is_personal:
        title = f"{inviter} invited you to their private meeting room"
    else:
        title = f"{inviter} invited you to a meeting of {target.label}"
    notify(
        invitation.invited_user,
        Category.MEETING_ROOM_INVITE,
        title=title,
        body=(invitation.note or "").strip(),
        url=target.room_url(),
        actor=_inviter(invitation),
        target=invitation,
    )


def invited_guest(invitation) -> None:
    """Email a guest their secret link, when an address was given."""
    if not invitation.guest_email:
        return
    target = inv.target_of(invitation)
    inviter = _inviter_name(invitation)
    context = {
        "host": inviter,
        "room_name": target.label,
        "is_personal": target.is_personal,
        "guest_name": invitation.guest_name,
        "note": (invitation.note or "").strip(),
        "join_url": invitation_url(invitation),
        "expires_at": invitation.expires_at,
    }
    subject = (
        f"{inviter} invited you to a meeting"
        if target.is_personal
        else f"{inviter} invited you to a meeting of {target.label}"
    )
    body = render_to_string("video/email/guest_invitation.txt", context)
    EmailMessage(
        subject=subject,
        body=body,
        from_email=school_from(),
        to=[invitation.guest_email],
        reply_to=_reply_to(invitation),
    ).send(fail_silently=True)


def send_invitation(invitation) -> None:
    """Whichever of the two applies."""
    if invitation.is_guest:
        invited_guest(invitation)
    else:
        invited_user(invitation)
