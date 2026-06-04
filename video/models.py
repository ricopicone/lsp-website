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
