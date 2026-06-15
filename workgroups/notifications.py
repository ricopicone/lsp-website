"""In-app notifications for group (workgroup) activity.

These events have no email today, so they're in-app-first: the GROUP_* category
defaults are bell-on / email-off (a member can opt into email per category on
the notification settings page). Every helper skips the actor so you're never
notified about your own action, and de-duplicates to avoid repeat spam.
"""

from __future__ import annotations

from notifications.categories import Category
from notifications.dispatch import notify


def _members(workgroup, *, exclude_id=None):
    """Yield active member users, optionally excluding one (the actor)."""
    for membership in workgroup.active_members():
        if membership.user_id == exclude_id:
            continue
        yield membership.user


def member_added(workgroup, user) -> None:
    """Tell ``user`` they were added to ``workgroup``."""
    notify(
        user, Category.GROUP_MEMBERSHIP,
        title=f"You were added to {workgroup.name}",
        url=workgroup.get_absolute_url(), target=workgroup, dedupe=True,
    )


def meeting_scheduled(meeting, actor=None) -> None:
    wg = meeting.workgroup
    url = f"{wg.get_absolute_url()}?tab=schedule"
    title = f"New meeting in {wg.name}"
    if getattr(meeting, "title", ""):
        title = f"{wg.name}: {meeting.title}"
    for user in _members(wg, exclude_id=getattr(actor, "id", None)):
        notify(
            user, Category.GROUP_MEETING, actor=actor,
            title=title, body=meeting.starts_at.strftime("%b %-d, %Y · %-I:%M %p"),
            url=url, target=meeting, dedupe=True,
        )


def series_scheduled(series, actor=None) -> None:
    wg = series.workgroup
    url = f"{wg.get_absolute_url()}?tab=schedule"
    for user in _members(wg, exclude_id=getattr(actor, "id", None)):
        notify(
            user, Category.GROUP_MEETING, actor=actor,
            title=f"A recurring meeting series was scheduled in {wg.name}",
            url=url, target=series, dedupe=True,
        )


def meeting_reminder(meeting) -> int:
    """Remind each active member ~15 min before ``meeting``. In-app bell links
    to the Meet tab; the email (sent only if the member's preference allows —
    they can opt out of GROUP_MEETING_REMINDER) carries a personal join link.
    Returns the number of members notified."""
    from . import emails

    wg = meeting.workgroup
    url = f"{wg.get_absolute_url()}?tab=meet"
    title = meeting.title or wg.name
    count = 0
    for user in _members(wg):
        notify(
            user, Category.GROUP_MEETING_REMINDER,
            title=f"Starting soon: {title}",
            body=meeting.starts_at.strftime("%-I:%M %p"),
            url=url, target=meeting,
            email_fn=(lambda u=user: emails.send_meeting_reminder(u, meeting)),
        )
        count += 1
    return count


def decision_recorded(decision, actor=None) -> None:
    wg = decision.workgroup
    url = f"{wg.get_absolute_url()}?tab=decisions"
    for user in _members(wg, exclude_id=getattr(actor, "id", None)):
        notify(
            user, Category.GROUP_DECISION, actor=actor,
            title=f"{wg.name}: {decision.title}",
            url=url, target=decision, dedupe=True,
        )


def minutes_posted(meeting, actor=None) -> None:
    wg = meeting.workgroup
    url = f"{wg.get_absolute_url()}?tab=minutes"
    for user in _members(wg, exclude_id=getattr(actor, "id", None)):
        notify(
            user, Category.GROUP_DECISION, actor=actor,
            title=f"Minutes posted in {wg.name}",
            url=url, target=meeting, dedupe=True,
        )


def recording_ready(recording) -> None:
    """A meeting recording finished processing. Only handles workgroup rooms;
    channel-only recordings are surfaced in the board instead."""
    wg = getattr(recording.room, "workgroup", None)
    if wg is None:
        return
    from django.urls import reverse

    url = reverse("video:recording_play", args=[recording.pk])
    for user in _members(wg):
        notify(
            user, Category.GROUP_RECORDING,
            title=f"A recording is ready in {wg.name}",
            url=url, target=recording, dedupe=True,
        )
