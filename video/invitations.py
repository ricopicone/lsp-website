"""What a room invitation is *to*, and how each kind of target behaves (task #694).

Three targets — a member's ``PersonalRoom`` (task #687), a ``Workgroup``, or a
one-off ``Event`` that owns its own room — differ in a handful of ways: who may
issue an invitation, who has to be in the room before an outsider may come in,
how long a guest link lives, and where an invited account holder goes once they
have signed in.

Every one of those differences is answered here, behind one uniform interface, so
that no call site branches on the target. A fact each surface re-derives for
itself is how ``Program.public_program_year_q()`` came to be written and never
called (task #532).

**The invariant this module exists to hold, for a room with no single owner:**

    A guest is never the first one in the room.

It binds every entrant ``services.can_enter`` does not already admit — an invited
account holder and an anonymous guest alike — so a forwarded or leaked link
reaches a doorstep saying the meeting has not started, never an empty room. A
personal room keeps its own stricter rule, that the *owner* specifically must be
present, in :mod:`video.services_personal`.
"""
from __future__ import annotations

from django.urls import reverse

from . import services
from .models import RoomInvitation


class EntryRefused(Exception):
    """Why someone may not join a room right now.

    ``waiting`` distinguishes the two refusals a doorstep must render very
    differently: *you may come in once the meeting starts* (True) from *this is
    not your room* (False).
    """

    def __init__(self, message: str, *, waiting: bool = False):
        super().__init__(message)
        self.message = message
        self.waiting = waiting


class Target:
    """One invitable room, behind a uniform interface."""

    is_personal = False

    def __init__(self, owner):
        self.owner = owner

    def __eq__(self, other):
        return type(self) is type(other) and self.owner == other.owner

    def __hash__(self):
        return hash((type(self).__name__, self.owner.pk))

    # ---- identity -------------------------------------------------------

    @property
    def kwargs(self) -> dict:
        """The FK kwarg that binds a ``RoomInvitation`` to this target."""
        raise NotImplementedError

    @property
    def label(self) -> str:
        """What an invitee is told they have been invited to."""
        raise NotImplementedError

    @property
    def invitations(self):
        return RoomInvitation.objects.filter(**self.kwargs)

    def live_invitations(self):
        return self.invitations.live().select_related("invited_user", "invited_by")

    # ---- policy ---------------------------------------------------------

    def may_invite(self, user) -> bool:
        """``services.is_owner`` — the site's one definition of "runs this
        meeting", already what grants the Daily moderator flag and the Record
        button. Reusing it rather than writing a leads-only twin keeps one answer
        to that question instead of two that must be kept in step."""
        return services.is_owner(self.owner, user)

    def default_expiry(self):
        """A group's invitations never expire; revoking is how one ends.

        Safe here in a way it would not be alone: the presence gate means a link
        by itself never opens an empty room, and a group's live invitations sit
        on its own Meet tab where every lead can see and revoke them. A flat TTL
        is what made a speaker invitation lapse eleven days before the event it
        was issued for (``events.speaker_invitations.invitation_expiry``).
        """
        return None

    def someone_present(self) -> bool:
        """Whether anybody is in the room right now.

        Reads the *existing* ``DailyRoom`` row, never ``ensure_room``: going
        through provisioning would create a Daily room for a group that has never
        met, and would turn a doorstep GET into a write.
        """
        return services.room_participant_count(getattr(self.owner, "video_room", None)) > 0

    def excluded_user_ids(self) -> set:
        """Who not to offer in the member picker, because they are already in."""
        raise NotImplementedError

    def room_url(self) -> str:
        """Where an invited account holder goes once signed in."""
        raise NotImplementedError

    def back_url(self) -> str:
        """Where managing an invitation returns to."""
        raise NotImplementedError


class WorkgroupTarget(Target):
    @property
    def kwargs(self):
        return {"workgroup": self.owner}

    @property
    def label(self):
        return self.owner.name

    def excluded_user_ids(self):
        # participants(), not active_members(): the latter returns stored rows
        # only, so a seminar's registrants and a committee's ex-officio officers
        # would be invisible and offered as though they were outsiders
        # (``active-members-vs-participants``).
        return {p.user.pk for p in self.owner.participants()}

    def room_url(self):
        return reverse("video:workgroup_room", args=[self.owner.slug])

    def back_url(self):
        return f"{self.owner.get_absolute_url()}?tab=meet"


class EventTarget(Target):
    """A one-off event that owns its own room (special event, Day of Assembly,
    Working Day, Scholarly Seminar)."""

    @property
    def kwargs(self):
        return {"event": self.owner}

    @property
    def label(self):
        return self.owner.title

    def excluded_user_ids(self):
        from registrations.models import Registration

        return set(
            Registration.objects.filter(
                event=self.owner,
                status__in=(Registration.Status.PAID, Registration.Status.COMPED),
            ).values_list("user_id", flat=True)
        )

    def room_url(self):
        return reverse("video:event_room", args=[self.owner.slug])

    def back_url(self):
        return f"{reverse('events:detail', args=[self.owner.slug])}?view=faculty"


class PersonalTarget(Target):
    is_personal = True

    @property
    def kwargs(self):
        return {"personal_room": self.owner}

    @property
    def label(self):
        from . import services_personal

        return services_personal.owner_display(self.owner)

    def may_invite(self, user) -> bool:
        """The room's own member, and nobody else — not even the site-technical
        roles, which are excluded from personal rooms entirely
        (``services_personal.can_enter_personal``). Unifying revoke across the
        three targets must not widen this."""
        return getattr(user, "pk", None) == self.owner.user_id

    def default_expiry(self):
        """A personal guest link keeps its 30 days (task #687)."""
        return RoomInvitation.default_expiry()

    def excluded_user_ids(self):
        return {self.owner.user_id}

    def room_url(self):
        return reverse("video:personal_room", args=[self.owner.slug])

    def back_url(self):
        return f"{reverse('formation:formation')}?tab=room"


def target_for(owner) -> Target:
    from events.models import Event
    from workgroups.models import Workgroup

    from .models import PersonalRoom

    if isinstance(owner, Workgroup):
        return WorkgroupTarget(owner)
    if isinstance(owner, Event):
        return EventTarget(owner)
    if isinstance(owner, PersonalRoom):
        return PersonalTarget(owner)
    raise TypeError(f"{owner!r} cannot own room invitations")


def target_for_event(event, *, create: bool = False) -> Target | None:
    """The target for the room ``event`` meets in.

    An offering event (seminar, reading group, cartel) meets in its *workgroup's*
    room, so it is never its own target: minting ``event``-target invitations for
    one would bind them to a room the event does not own, and they would admit
    nobody. ``services.room_owner_for_event`` is the one place that distinction
    is made; asking it here is what keeps this from becoming a second copy.
    """
    owner = services.room_owner_for_event(event, create=create)
    return None if owner is None else target_for(owner)


def target_of(invitation) -> Target:
    return target_for(invitation.target_object)


# ---- entry --------------------------------------------------------------

def invitation_for(target, user):
    """``user``'s live account-bound invitation to ``target``, if any."""
    if not getattr(user, "is_authenticated", False):
        return None
    return target.invitations.live().filter(invited_user=user).first()


def guest_invitation(token: str):
    """The live guest invitation a secret URL names, or None.

    Not single-use and not consumed by looking: email link-scanners pre-click
    links on exactly the addresses this gets mailed to
    (``auth-email-scanner-and-reset-gotchas``), and a rescheduled meeting wants
    the same link twice. Revoking is how one ends early.
    """
    if not token:
        return None
    return (
        RoomInvitation.objects.live()
        .filter(token=token)
        .select_related("personal_room", "personal_room__user", "workgroup", "event")
        .first()
    )


def _admits(invitation) -> bool:
    """Re-checked rather than trusted, so a caller that fetched an invitation
    without filtering ``live()`` cannot subvert the gate. The check costs nothing
    (``is_live`` reads fields already loaded) and means no future call site has to
    remember the rule."""
    return invitation is not None and invitation.is_live


def check_entry(target, user, *, invitation=None) -> None:
    """Raise :class:`EntryRefused` unless ``user`` may join ``target`` right now.

    The group rule. A personal room's stricter one lives in
    ``services_personal.check_entry``, and routing a personal target here would
    silently relax it, so this refuses one outright.
    """
    if target.is_personal:
        raise TypeError("a personal room goes through services_personal.check_entry")
    if services.can_enter(target.owner, user):
        return
    if not _admits(invitation) and invitation_for(target, user) is None:
        raise EntryRefused(
            "This is a private meeting room, and you have not been invited to it."
        )
    if not target.someone_present():
        raise EntryRefused(
            f"The meeting in {target.label} has not started yet.", waiting=True
        )


def guest_token(daily_room, guest_name: str, **kwargs) -> str:
    """A non-owner Daily token carrying the display name a guest typed.

    ``services.mint_token`` derives the name from a ``User`` and a guest has
    none, so this is the one place that reaches the Daily client directly.
    """
    import time

    from django.conf import settings

    from . import daily as daily_api

    exp = kwargs.pop("exp", None) or (
        int(time.time()) + settings.DAILY_TOKEN_TTL_MINUTES * 60
    )
    return daily_api.create_meeting_token(
        room_name=daily_room.name, user_name=guest_name[:255], is_owner=False,
        exp=exp, **kwargs,
    )


# ---- the management panel -----------------------------------------------

def panel_context(target, *, user, post_url, heading, intro):
    """Context for ``video/_invitations_panel.html``, or None when ``user`` may
    not invite. One shared partial rather than one per surface: two copies of a
    form's validation and copy drift.
    """
    if not target.may_invite(user):
        return None
    from .forms_invitations import InvitationForm
    from .notifications_invitations import invitation_url

    rows = list(target.live_invitations().order_by("-created_at"))
    for row in rows:
        # Only a guest has a link to hand over; an account holder follows the
        # ordinary room URL after signing in.
        row.share_url = invitation_url(row) if row.is_guest else ""
    return {
        "form": InvitationForm(target=target),
        "invitations": rows,
        "post_url": post_url,
        "heading": heading,
        "intro": intro,
    }
