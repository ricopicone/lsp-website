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
                    Q(workgroup__isnull=False, channel__isnull=True)
                    | Q(workgroup__isnull=True, channel__isnull=False)
                ),
                name="video_room_exactly_one_owner",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def owner(self):
        return self.workgroup or self.channel


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
        PUBLIC = "public", "Public"
        MEMBERS = "members", "Members (all LSP)"
        REGISTRANTS = "registrants", "Registrants only"
        GROUP = "group", "Group members only"
        STAFF = "staff", "Staff only (private)"

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
    started_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)

    listing_visibility = models.CharField(
        max_length=12, choices=Visibility.choices, default=Visibility.STAFF,
        help_text="Who sees that this recording exists (e.g. on the event page).",
    )
    content_visibility = models.CharField(
        max_length=12, choices=Visibility.choices, default=Visibility.STAFF,
        help_text="Who can watch it. Cannot be more public than the listing.",
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

    _VISIBILITY_RANK = {
        Visibility.PUBLIC: 4,
        Visibility.MEMBERS: 3,
        Visibility.REGISTRANTS: 2,
        Visibility.GROUP: 1,
        Visibility.STAFF: 0,
    }

    def _workgroup(self):
        return self.room.workgroup if self.room_id else None

    def _can_host(self, user) -> bool:
        if self.event_id:
            from events.permissions import can_edit_event
            return can_edit_event(user, self.event)
        wg = self._workgroup()
        if wg is None:
            return getattr(user, "is_staff", False)
        from workgroups.models import WorkgroupMembership
        return (
            getattr(user, "is_staff", False)
            or wg.memberships.serving().filter(
                user=user, role__in=WorkgroupMembership.LEAD_ROLES
            ).exists()
        )

    def _visible_at(self, level, user) -> bool:
        if level == self.Visibility.PUBLIC:
            return True
        if not getattr(user, "is_authenticated", False):
            return False
        if level == self.Visibility.STAFF:
            return self._can_host(user)
        if level == self.Visibility.GROUP:
            wg = self._workgroup()
            in_group = bool(wg and (wg.is_member(user) or wg.has_archive_access(user)))
            return in_group or self._can_host(user)
        if level == self.Visibility.REGISTRANTS:
            return (
                bool(self.event_id and self.event.has_access_registrant(user))
                or self._can_host(user)
            )
        from accounts.permissions import is_lsp_member
        return is_lsp_member(user)  # MEMBERS

    def listing_visible_to(self, user) -> bool:
        return self._visible_at(self.listing_visibility, user)

    def content_visible_to(self, user) -> bool:
        return self._visible_at(self.content_visibility, user)

    def clean(self):
        from django.core.exceptions import ValidationError

        rank = self._VISIBILITY_RANK
        if rank[self.content_visibility] > rank[self.listing_visibility]:
            raise ValidationError(
                {"content_visibility": "The recording can't be more watchable than it is listed."}
            )

    # ---- playback ----

    def playable_url(self):
        """A temporary URL to stream/download the recording, or None if not ready."""
        from django.conf import settings

        from . import daily

        if self.status != self.Status.READY:
            return None
        if getattr(settings, "RECORDING_OWN_S3", False) and self.s3_key:
            from core.storage import recordings_storage
            return recordings_storage().url(self.s3_key)
        try:
            return daily.recording_access_link(self.daily_recording_id)
        except daily.DailyError:
            return None
