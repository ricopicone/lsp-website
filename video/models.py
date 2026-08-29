"""Daily.co video rooms — one persistent, site-owned room per Workgroup.

A seminar (Event + its recurring Sessions), cartel, committee, working group,
or reading group all attach a ``workgroups.Workgroup``; the meeting room hangs
off that Workgroup so the *same* room is reused for every session/meeting (the
stable recurring link). Rooms are provisioned lazily on first join (see
``video.services.ensure_room``) and gated by the workgroup's existing
membership rules — see the ``video-daily-integration`` design.
"""
from __future__ import annotations

from django.db import models
from django.db.models import Q


class DailyRoom(models.Model):
    """A provisioned Daily.co room bound to a single owner.

    The owner is either a Workgroup (the group's persistent room, surfaced on the
    Meet tab) or a standalone Parlêtre Channel (a board-level video channel). A
    workgroup-access video channel reuses its workgroup's room, so the ``channel``
    owner is used only for non-workgroup channels.
    """

    workgroup = models.OneToOneField(
        "workgroups.Workgroup",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="video_room",
    )
    channel = models.OneToOneField(
        "parletre.Channel",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="video_room",
    )
    #: A one-off event (special event / Day of Assembly / Working Day / Scholarly
    #: Seminar) owns its own room rather than sharing the Programming Committee's
    #: workgroup room. Offering events (seminar/reading_group/cartel) still use
    #: their own workgroup's room, so this is null for them.
    event = models.OneToOneField(
        "events.Event",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="video_room",
    )
    #: A member's private meeting room (task #687). Owned by the PersonalRoom
    #: rather than the User directly, so the room's settings (recording mode,
    #: office hours) hang off one object and ``services`` keeps reading
    #: ``owner.slug`` / ``owner.recording_mode`` with no branch for it.
    personal_room = models.OneToOneField(
        "video.PersonalRoom",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="video_room",
    )
    #: The Daily room name (the trailing path segment of the join URL).
    name = models.CharField(max_length=128, unique=True)
    #: Full join URL, e.g. ``https://lsp.daily.co/lsp-<slug>``.
    url = models.URLField(max_length=500)
    #: True once the room is confirmed created on Daily's side. Lets us keep a
    #: row but re-provision if the remote room was deleted.
    provider_created = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Daily room"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(workgroup__isnull=False, channel__isnull=True,
                      event__isnull=True, personal_room__isnull=True)
                    | Q(workgroup__isnull=True, channel__isnull=False,
                        event__isnull=True, personal_room__isnull=True)
                    | Q(workgroup__isnull=True, channel__isnull=True,
                        event__isnull=False, personal_room__isnull=True)
                    | Q(workgroup__isnull=True, channel__isnull=True,
                        event__isnull=True, personal_room__isnull=False)
                ),
                name="video_room_exactly_one_owner",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def owner(self):
        return self.workgroup or self.channel or self.event or self.personal_room


class Recording(models.Model):
    """A cloud recording of a meeting in a ``DailyRoom``.

    Storage-agnostic: ``daily_recording_id`` is the source of truth; ``s3_key`` is
    populated when recordings are stored in our own bucket. ``playable_url`` resolves
    either. Visibility mirrors works.Work (listing vs content)."""

    class Status(models.TextChoices):
        RECORDING = "recording", "Recording"
        READY = "ready", "Ready"
        ERROR = "error", "Error"
        DELETED = "deleted", "Deleted"

    class Visibility(models.TextChoices):
        """Who a recording is available to (task #475).

        Two independent dimensions — *registration* (on the roster or not) and
        *membership* (an LSP member or merely an account holder) — so these do
        NOT form a ladder: ``ROSTER`` and ``MEMBERS`` are incomparable, since a
        registered external attendee is in one and an unregistered member in the
        other. ``_CONTAINS`` below is the real containment relation; don't
        reintroduce an integer rank.
        """

        OWNERS = "owners", "Unavailable (owners only)"
        ROSTER_MEMBERS = "roster_members", "Registered group members who are LSP Members"
        ROSTER = "roster", "Registered group members"
        MEMBERS = "members", "LSP Members"
        ACCOUNTS = "accounts", "LSP Members and Auditors"
        PUBLIC = "public", "Public"

    room = models.ForeignKey(
        DailyRoom, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="recordings",
    )
    event = models.ForeignKey(
        "events.Event", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="recordings",
    )
    started_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="started_recordings",
    )

    daily_recording_id = models.CharField(max_length=128, unique=True)
    room_name = models.CharField(max_length=128, blank=True)
    s3_key = models.CharField(max_length=512, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RECORDING)
    title = models.CharField(max_length=200, blank=True)
    note = models.TextField(blank=True, help_text="Notes / annotation for this recording.")
    started_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)

    listing_visibility = models.CharField(
        max_length=16, choices=Visibility.choices, default=Visibility.OWNERS,
        help_text="Who sees that this recording exists (e.g. on the event page).",
    )
    content_visibility = models.CharField(
        max_length=16, choices=Visibility.choices, default=Visibility.OWNERS,
        help_text="Who can watch it. Must be contained in the listing audience.",
    )
    keep = models.BooleanField(
        default=False, help_text="Exempt from automatic retention deletion.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-started_at", "-created_at")

    def __str__(self) -> str:
        return self.title or self.daily_recording_id

    # ---- visibility (mirrors works.Work) ----

    #: Each setting decomposed into the two independent dimensions it actually
    #: constrains: how much standing a viewer needs, and whether they must be on
    #: the roster. Making those explicit is what lets ``_meet`` combine two
    #: settings arithmetically instead of by lookup table — and it is why the six
    #: settings are closed under intersection (every intersection of two of them
    #: is itself one of the six, so an effective audience always has a name).
    _ANON, _ACCOUNT, _MEMBER = 0, 1, 2
    _DIMENSIONS = {
        Visibility.PUBLIC: (_ANON, False),
        Visibility.ACCOUNTS: (_ACCOUNT, False),
        Visibility.MEMBERS: (_MEMBER, False),
        Visibility.ROSTER: (_ACCOUNT, True),
        Visibility.ROSTER_MEMBERS: (_MEMBER, True),
        # OWNERS is the empty audience — no amount of standing qualifies — so it
        # has no decomposition and is handled directly in _meet.
    }

    @classmethod
    def _meet(cls, a, b):
        """Everyone in BOTH audiences, as one of the six settings.

        Standing takes the stricter of the two; the roster requirement is the
        OR. So "LSP Members" ∩ "Registered group members" is "Registered group
        members who are LSP Members" — the combination that has no ordering
        between its parts is exactly the one that names their intersection.
        """
        V = cls.Visibility
        if V.OWNERS in (a, b):
            return V.OWNERS
        standing_a, roster_a = cls._DIMENSIONS[a]
        standing_b, roster_b = cls._DIMENSIONS[b]
        target = (max(standing_a, standing_b), roster_a or roster_b)
        for level, dimensions in cls._DIMENSIONS.items():
            if dimensions == target:
                return level
        raise AssertionError(f"unreachable: {target} is not one of the six")  # pragma: no cover

    @property
    def effective_visibility(self):
        """Who can actually watch this: the intersection of the two settings."""
        return self._meet(self.listing_visibility, self.content_visibility)

    @property
    def effective_visibility_label(self) -> str:
        return self.Visibility(self.effective_visibility).label

    def _workgroup(self):
        return self.room.workgroup if self.room_id else None

    @property
    def is_personal(self) -> bool:
        """Made in a member's private meeting room (task #687).

        Such a recording has neither an event nor a workgroup, so the six
        visibility settings do not apply to it — two of them are defined by
        roster membership and a personal room has no roster. It stays at the
        ``OWNERS`` default and the availability form is not offered.
        """
        return bool(self.room_id and self.room.personal_room_id)

    def _personal_owner_id(self):
        return self.room.personal_room.user_id if self.is_personal else None

    def _can_host(self, user) -> bool:
        """Who runs this recording's meeting — the single definition, shared with
        the room's moderator flag, so "can moderate" and "can manage the
        recording" can't drift apart."""
        from . import services

        if getattr(user, "is_staff", False):
            return True
        # A personal room's recording belongs to its member, and to nobody else.
        # Without this the fallback below would hand it to the site-technical
        # roles while leaving the member unable to watch their own recording —
        # and those roles are deliberately excluded from personal rooms
        # entirely (see services_personal.can_enter_personal).
        if self.is_personal:
            return getattr(user, "pk", None) == self._personal_owner_id()
        if self.event_id:
            owner = services.room_owner_for_event(self.event) or self.event
            return services.is_owner(owner, user)
        wg = self._workgroup()
        if wg is None:
            return services.is_site_technical(user)
        # services.is_owner is the one definition of "runs this meeting": the
        # site-technical roles, the event's hosts, and (task #480) any workgroup
        # lead including the derived school officers. Delegating keeps recording
        # management and room moderation from drifting apart.
        return services.is_owner(wg, user)

    def _in_roster(self, user) -> bool:
        """On this recording's roster: an event's paid/comped registrants, or a
        group's members (``Workgroup.is_member`` already means the right thing
        for both — derived registrants for an offering, the stored roster for a
        cartel or committee)."""
        if self.event_id and self.event.has_access_registrant(user):
            return True
        wg = self._workgroup()
        return bool(wg and (wg.is_member(user) or wg.has_archive_access(user)))

    def _visible_at(self, level, user) -> bool:
        if level == self.Visibility.PUBLIC:
            return True
        if not getattr(user, "is_authenticated", False):
            return False
        # Whoever runs the meeting sees its recording at every level — including
        # MEMBERS, which used to have no host fallback and so hid an external
        # speaker's own talk from them.
        if self._can_host(user):
            return True
        if level == self.Visibility.ACCOUNTS:
            return True
        from accounts.permissions import is_lsp_member

        if level == self.Visibility.MEMBERS:
            return is_lsp_member(user)
        if level == self.Visibility.ROSTER:
            return self._in_roster(user)
        if level == self.Visibility.ROSTER_MEMBERS:
            return self._in_roster(user) and is_lsp_member(user)
        return False  # OWNERS

    def listing_visible_to(self, user) -> bool:
        return self._visible_at(self.listing_visibility, user)

    def content_visible_to(self, user) -> bool:
        """Both settings must admit you — you cannot watch what you cannot see
        exists. Enforcing that here rather than in ``clean()`` makes it
        structural: a raw ``QuerySet.update()`` (which skips validation, and
        which our own data migrations use) can't produce a leaking pair."""
        return self._visible_at(self.listing_visibility, user) and self._visible_at(
            self.content_visibility, user
        )

    def can_manage(self, user) -> bool:
        """Whether ``user`` may manage this recording (keep / annotate / delete) —
        its host (faculty/lead) or staff."""
        return self._can_host(user)

    def delete_everywhere(self):
        """Delete the S3 object + the Daily recording + this row."""
        from . import daily

        if self.s3_key:
            try:
                from core.storage import recordings_storage

                recordings_storage().delete(self.s3_key)
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass
        try:
            daily.delete_recording(self.daily_recording_id)
        except daily.DailyError:
            pass
        self.delete()

    # No clean() guard on the visibility pair: the two settings intersect rather
    # than compete, so every combination is meaningful. See ``_meet``.

    # ---- playback ----

    def playable_url(self, *, download: bool = False):
        """A temporary URL to stream/download the recording, or None if not ready.
        Presigned from our S3 (owned mode) else Daily's access-link."""
        from django.conf import settings

        from . import daily

        if self.status != self.Status.READY:
            return None
        if getattr(settings, "RECORDING_OWN_S3", False) and self.s3_key:
            from core.storage import presigned_recordings_url
            return presigned_recordings_url(self.s3_key, download=download)
        try:
            return daily.recording_access_link(self.daily_recording_id)
        except daily.DailyError:
            return None


def _invitation_token() -> str:
    """An opaque, unguessable secret for a guest invitation URL."""
    import secrets

    return secrets.token_urlsafe(32)


def _personal_slug() -> str:
    """An opaque slug for a personal room.

    Deliberately *not* the member's ``directory_slug``: the Daily room name rides
    in the iframe URL where a guest can read it, and a one-off guest has no
    business learning a member's directory handle from the page furniture.
    """
    import secrets

    return f"pr-{secrets.token_hex(8)}"


class PersonalRoom(models.Model):
    """One member's private meeting room (task #687).

    Owns a :class:`DailyRoom` the way a Workgroup, Channel or one-off Event does,
    and satisfies the same duck-typed protocol ``video.services`` reads through
    ``getattr`` — ``.slug`` for the room name and ``.recording_mode`` for the
    Daily config — so ``_room_name`` and ``_desired_properties`` need no branch
    for it.

    Rooms are created lazily on the member's first visit to their own room page;
    nothing is provisioned in advance and there is no backfill. A member with no
    invitations and office hours off has a room only they can enter, which is why
    there is no separate "enabled" switch: it would add a state (disabled room,
    live invitations) whose behaviour someone would then have to define.
    """

    class RecordingMode(models.TextChoices):
        OFF = "off", "No recording"
        ON_DEMAND = "on_demand", "I can record"

    class OfficeHours(models.TextChoices):
        """Whether the door is open, not merely how it is labelled.

        ``APPOINTMENT`` advertises without admitting anyone — that is what makes
        "by appointment" mean something rather than being a label on an open
        door. See ``services_personal.can_enter_personal``.
        """

        OFF = "off", "Not shown"
        POSTED = "posted", "Posted hours, members may join"
        APPOINTMENT = "appointment", "By appointment only"

    user = models.OneToOneField(
        "accounts.User", on_delete=models.CASCADE, related_name="personal_room",
    )
    slug = models.CharField(max_length=64, unique=True, default=_personal_slug, editable=False)
    recording_mode = models.CharField(
        max_length=16, choices=RecordingMode.choices, default=RecordingMode.OFF,
        help_text=(
            "Off by default, unlike every other room here: this room holds "
            "interviews and office hours, and a Record button does not belong in "
            "one unasked."
        ),
    )
    office_hours = models.CharField(
        max_length=16, choices=OfficeHours.choices, default=OfficeHours.OFF,
    )
    hours_note = models.CharField(
        max_length=200, blank=True,
        help_text="Free text, e.g. 'Thursdays 3-4pm Pacific' or 'after seminar, or write to me'.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "personal meeting room"

    def __str__(self) -> str:
        return f"{self.user} — private meeting room"

    @property
    def advertises_hours(self) -> bool:
        """Whether anything is shown on the Workspace / directory surfaces."""
        return self.office_hours != self.OfficeHours.OFF and bool(self.hours_note.strip())

    @property
    def admits_members(self) -> bool:
        """Whether an uninvited LSP member may walk in (while the owner is here)."""
        return self.office_hours == self.OfficeHours.POSTED

    def live_invitations(self, now=None):
        return self.invitations.live(now)


class RoomInvitationQuerySet(models.QuerySet):
    def live(self, now=None):
        from django.utils import timezone

        now = now or timezone.now()
        return self.filter(revoked_at__isnull=True, expires_at__gt=now)


class RoomInvitation(models.Model):
    """Someone the member has let into their personal room.

    Two kinds, exactly one of which is set — the constraint style ``DailyRoom``
    already uses for its owners:

    * **internal** — ``invited_user``, an account (member or not, so an applicant
      being interviewed is reachable by name rather than by secret link). They
      sign in as themselves.
    * **guest** — ``token``, the secret in a ``/meet/g/<token>/`` URL, for
      someone with no account at all.

    Neither is single-use: office hours and a rescheduled interview both want the
    same link twice, and email link-scanners pre-click links on exactly the
    addresses this gets mailed to. Revoking is how an invitation ends early.

    An invitation is never sufficient on its own — see the invariant in
    ``services_personal.can_enter_personal``: nobody but the owner is in a
    personal room unless the owner is in it.
    """

    #: Long enough for a scheduled interview to be arranged and rescheduled,
    #: short enough that a room does not accumulate a standing list of everyone
    #: its owner has ever met.
    DEFAULT_TTL_DAYS = 30

    room = models.ForeignKey(
        PersonalRoom, on_delete=models.CASCADE, related_name="invitations",
    )
    invited_user = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.CASCADE,
        related_name="room_invitations",
    )
    token = models.CharField(max_length=64, unique=True, null=True, blank=True)
    guest_name = models.CharField(max_length=120, blank=True)
    guest_email = models.EmailField(blank=True)
    note = models.CharField(
        max_length=200, blank=True, help_text="Shown to the person you invited.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    objects = RoomInvitationQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(invited_user__isnull=False, token__isnull=True)
                    | Q(invited_user__isnull=True, token__isnull=False)
                ),
                name="video_invitation_exactly_one_kind",
            ),
        ]

    def __str__(self) -> str:
        return f"invitation to {self.display_name} ({'live' if self.is_live else 'ended'})"

    @property
    def is_guest(self) -> bool:
        return self.token is not None

    @property
    def display_name(self) -> str:
        if self.invited_user_id:
            return self.invited_user.get_full_name() or self.invited_user.email
        return self.guest_name or "Guest"

    def is_expired(self, now=None) -> bool:
        from django.utils import timezone

        return (now or timezone.now()) >= self.expires_at

    @property
    def is_live(self) -> bool:
        return self.revoked_at is None and not self.is_expired()

    def revoke(self) -> None:
        from django.utils import timezone

        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])

    def touch(self) -> None:
        from django.utils import timezone

        self.last_used_at = timezone.now()
        self.save(update_fields=["last_used_at"])

    @classmethod
    def new_token(cls) -> str:
        """A fresh guest secret. Here rather than in the form, so every caller
        that mints one reaches the same generator."""
        return _invitation_token()

    @classmethod
    def default_expiry(cls, now=None):
        import datetime as _dt

        from django.utils import timezone

        return (now or timezone.now()) + _dt.timedelta(days=cls.DEFAULT_TTL_DAYS)
