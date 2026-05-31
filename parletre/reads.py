"""Unread tracking for Parlêtre (DISC-4).

Read state is a watermark per (member, thread) for forums and per
(member, channel) for chat. A thread is unread when its ``last_activity_at``
is newer than the member's marker (or there's no marker yet). These helpers
keep the query count bounded — a handful of queries on the index, regardless
of channel count.
"""

from __future__ import annotations

from django.db.models import Max
from django.utils import timezone

from .models import Post, ReadMarker, Thread


def mark_thread_read(user, thread, when=None) -> None:
    ReadMarker.objects.update_or_create(
        user=user, thread=thread, defaults={"last_read_at": when or timezone.now()}
    )


def mark_channel_read(user, channel, when=None) -> None:
    ReadMarker.objects.update_or_create(
        user=user, channel=channel, thread=None,
        defaults={"last_read_at": when or timezone.now()},
    )


def thread_marker_at(user, thread):
    """The member's last-read time for ``thread``, or None if never read."""
    marker = ReadMarker.objects.filter(user=user, thread=thread).first()
    return marker.last_read_at if marker else None


def unread_thread_ids(user, channel) -> set[int]:
    """IDs of threads in ``channel`` that are unread for ``user``."""
    seen = {
        tid: ts
        for tid, ts in ReadMarker.objects.filter(
            user=user, thread__channel=channel, thread__isnull=False
        ).values_list("thread_id", "last_read_at")
    }
    unread = set()
    for tid, last_act in channel.threads.values_list("id", "last_activity_at"):
        ts = seen.get(tid)
        if ts is None or last_act > ts:
            unread.add(tid)
    return unread


def unread_channel_ids(user, channels) -> set[int]:
    """IDs of channels (from ``channels``) that have unread activity."""
    if not channels:
        return set()
    forum_ids = [c.id for c in channels if c.is_forum]
    chat_ids = [c.id for c in channels if not c.is_forum]

    markers = list(ReadMarker.objects.filter(user=user).values(
        "thread_id", "channel_id", "last_read_at"
    ))
    thread_seen = {m["thread_id"]: m["last_read_at"] for m in markers if m["thread_id"]}
    channel_seen = {
        m["channel_id"]: m["last_read_at"]
        for m in markers if m["channel_id"] and not m["thread_id"]
    }

    unread: set[int] = set()
    if forum_ids:
        for cid, tid, last_act in Thread.objects.filter(
            channel_id__in=forum_ids
        ).values_list("channel_id", "id", "last_activity_at"):
            ts = thread_seen.get(tid)
            if ts is None or last_act > ts:
                unread.add(cid)
    if chat_ids:
        latest = (
            Post.objects.filter(channel_id__in=chat_ids, thread__isnull=True)
            .values("channel_id")
            .annotate(latest=Max("created_at"))
        )
        for row in latest:
            ts = channel_seen.get(row["channel_id"])
            if ts is None or row["latest"] > ts:
                unread.add(row["channel_id"])
    return unread
