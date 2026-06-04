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


class DailyRoom(models.Model):
    """A provisioned Daily.co room bound to a single Workgroup."""

    workgroup = models.OneToOneField(
        "workgroups.Workgroup",
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

    def __str__(self) -> str:
        return self.name
