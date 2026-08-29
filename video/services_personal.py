"""A member's private meeting room: who has one, and who may be in it (task #687).

Kept beside :mod:`video.services` rather than inside it because a personal room
answers "who may enter" with a rule the group rooms do not share, and folding it
in would put a fourth arm on predicates that are already three-way polymorphic.
Provisioning still goes through ``services.ensure_room``: a ``PersonalRoom``
supplies ``.slug`` and ``.recording_mode``, which is the whole protocol that
function reads.

**The invariant, which everything here exists to hold:**

    Nobody but the owner is in a personal room unless the owner is in it.

It applies to every entrant without exception — an invited member, an invited
account holder, an anonymous guest, a member walking in during posted office
hours. A leaked or forwarded invitation link therefore cannot put a stranger
alone in someone's room; the worst it can do is put them at a doorstep that says
the meeting has not started.

The check is made when the token is minted. Daily does not eject at token expiry
(``eject_at_token_exp`` defaults false), so someone already in the room stays if
the owner's connection drops for a moment — the same behaviour a knock-to-enter
lobby has, and the one we want.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from . import services
from .models import PersonalRoom, RoomInvitation

logger = logging.getLogger("video")


class EntryRefused(Exception):
    """Why someone may not join a personal room right now.

    ``waiting`` distinguishes the two refusals a doorstep must render very
    differently: *you may come in once the host arrives* (True) from *this is not
    your room* (False).
    """

    def __init__(self, message: str, *, waiting: bool = False):
        super().__init__(message)
        self.message = message
        self.waiting = waiting


def eligible_for_room(user) -> bool:
    """Whether ``user`` gets a room of their own.

    ``is_lsp_member`` — the one definition of membership, as everywhere else. An
    Auditor, Student, Prospective Applicant or bare account holder does not get a
    room, which is what "each member (not non-member users)" asks for. They can
    still be invited into someone else's.
    """
    from accounts.permissions import is_lsp_member

    return is_lsp_member(user)


def personal_room_for(user, *, create: bool = False) -> PersonalRoom | None:
    """The member's ``PersonalRoom``, optionally creating it.

    Created lazily on their first visit to their own room page, so nothing is
    provisioned for members who never open it and there is no backfill.
    """
    if not getattr(user, "is_authenticated", False):
        return None
    room = PersonalRoom.objects.filter(user=user).first()
    if room is not None or not create:
        return room
    if not eligible_for_room(user):
        return None
    return PersonalRoom.objects.create(user=user)


def owner_present(room: PersonalRoom) -> bool:
    """Whether the room's member is in it right now.

    Reads the account-wide presence map ``services`` already caches for ~20s, so
    a host who joined seconds ago may not register yet and the doorstep polls.
    Deliberately not primed when we mint the owner's token: they may never clear
    the prejoin screen, and a doorstep that says "your host is here" when nobody
    is would be worse than one that lags.
    """
    daily_room = getattr(room, "video_room", None)
    if daily_room is None:
        return False
    return services.room_participant_count(daily_room) > 0


def invitation_for(room: PersonalRoom, user) -> RoomInvitation | None:
    """``user``'s live internal invitation to ``room``, if any."""
    if not getattr(user, "is_authenticated", False):
        return None
    return room.invitations.live().filter(invited_user=user).first()


def guest_invitation(token: str) -> RoomInvitation | None:
    """The live guest invitation a secret URL names, or None.

    Not single-use and not consumed by looking: office hours and a rescheduled
    interview both want the same link twice, and email link-scanners pre-click
    links on exactly the addresses this gets mailed to
    (``auth-email-scanner-and-reset-gotchas``). Revoking is how one ends early.
    """
    if not token:
        return None
    return RoomInvitation.objects.live().filter(token=token).select_related(
        "room", "room__user"
    ).first()


def may_be_admitted(room: PersonalRoom, user) -> bool:
    """Whether ``user`` is someone this room admits *at all*, ignoring presence.

    Three ways in, and the site-technical roles are deliberately not among them —
    see :func:`can_enter_personal`.
    """
    if invitation_for(room, user) is not None:
        return True
    # Posted office hours open the door to members; "by appointment" advertises
    # without admitting anyone, which is what makes the label mean something.
    return bool(room.admits_members and eligible_for_room(user))


def can_enter_personal(room: PersonalRoom, user, *, invitation=None) -> bool:
    """Whether ``user`` may join ``room`` right now.

    The owner always may. Everyone else must be admitted *and* find the owner
    already in the room.

    **The Web Coordinator and Web Developer are excluded**, departing from
    ``services.is_site_technical``, which lets them enter and moderate every
    other meeting on the site so someone can help when an event goes wrong. This
    is the exception for the reason ``can_enter_channel`` already excludes them
    from Parlêtre private channels: a private channel is private even from staff
    (task #360). Widening entry here would break the same promise, and the
    promise is the feature. Do not "fix" this omission.
    """
    if getattr(user, "is_authenticated", False) and user.pk == room.user_id:
        return True
    admitted = invitation is not None or may_be_admitted(room, user)
    return bool(admitted and owner_present(room))


def check_entry(room: PersonalRoom, user, *, invitation=None) -> None:
    """:func:`can_enter_personal`, raising :class:`EntryRefused` with copy that
    says which of the two refusals it is."""
    if getattr(user, "is_authenticated", False) and user.pk == room.user_id:
        return
    if invitation is None and not may_be_admitted(room, user):
        raise EntryRefused("This is a private meeting room, and you have not been invited to it.")
    if not owner_present(room):
        raise EntryRefused(
            f"{owner_display(room)} has not started the meeting yet.", waiting=True,
        )


def owner_display(room: PersonalRoom) -> str:
    return room.user.get_full_name() or "Your host"


def room_context(request, room: PersonalRoom, *, is_owner: bool, guest_name: str = "") -> dict:
    """Everything ``video/room.html`` needs, or ``{"room_unavailable": True}``.

    Mirrors ``services.channel_room_context``. ``guest_name`` names an anonymous
    participant in the People panel, so the member sees a person rather than a
    row of "Guest".
    """
    daily_room = services.ensure_room(room)
    if daily_room is None:
        return {"room_unavailable": True}
    user = getattr(request, "user", None)
    try:
        if guest_name:
            token = _guest_token(daily_room, guest_name)
        else:
            token = services.mint_token(daily_room, user, is_owner=is_owner)
    except Exception:  # noqa: BLE001 — degrade to the unavailable state
        logger.exception("Daily token mint failed for personal room %s", room.slug)
        return {"room_unavailable": True}
    return {
        "room_url": daily_room.url,
        "token": token,
        "is_owner": is_owner,
        "recording_available": room.recording_mode != PersonalRoom.RecordingMode.OFF,
        "personal_room": room,
    }


def _guest_token(daily_room, guest_name: str) -> str:
    """A non-owner token carrying the display name a guest gave us.

    ``services.mint_token`` derives the name from a ``User``, and a guest has
    none, so this is the one place that reaches the Daily client directly.
    """
    import time

    from django.conf import settings

    from . import daily as daily_api

    exp = int(time.time()) + settings.DAILY_TOKEN_TTL_MINUTES * 60
    return daily_api.create_meeting_token(
        room_name=daily_room.name, user_name=guest_name[:255], is_owner=False, exp=exp,
    )


# ---- office hours -------------------------------------------------------

def hours_for(user) -> PersonalRoom | None:
    """The room whose office hours should be advertised for ``user``, or None.

    Returns the room itself so a template can render the note and decide about a
    Join button from one object.
    """
    room = getattr(user, "personal_room", None)
    if room is None:
        return None
    return room if room.advertises_hours else None


def offering_hours(event) -> list:
    """``(user, room)`` for everyone running ``event`` who advertises hours.

    ``events.permissions.offering_leads`` is the audience, not
    ``faculty_members()``: a reading group's conveners hold ORGANIZER rather than
    FACULTY (task #495), and using the narrower list is the defect task #564 had
    to fix in the approval notice.
    """
    from events.permissions import offering_leads

    rows = []
    for person in offering_leads(event):
        room = hours_for(person)
        if room is not None:
            rows.append((person, room))
    return rows


def touch_invitation(invitation) -> None:
    if invitation is not None:
        invitation.touch()


def new_expiry():
    return RoomInvitation.default_expiry(timezone.now())
