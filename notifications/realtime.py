"""Realtime push for the nav bell.

When a notification is raised, :func:`broadcast_to_user` pushes the live unread
count (and a small preview of the new item) to the recipient's personal
Channels group, so an open tab updates the badge without a reload. The channel
layer is in-memory in production (single daphne process), so this is a
best-effort, same-process broadcast — a missing layer is a silent no-op.
"""

from __future__ import annotations

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def user_group(user_id: int) -> str:
    return f"notif_user_{user_id}"


def broadcast_to_user(user_id: int, *, unread: int, item: dict | None = None) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(layer.group_send)(
        user_group(user_id),
        {"type": "notify.event", "unread": unread, "item": item},
    )
