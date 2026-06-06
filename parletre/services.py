"""Side-effects of posting in Parlêtre: @mention parsing, in-app
notifications (the nav bell), and immediate notification emails.

Email follows each member's per-channel subscription level:

* ``all``           → email on every post
* ``threads_only``  → email on each new thread
* ``mentions_only`` → email only when @mentioned
* ``digest``        → no immediate email; batched by send_discussion_digests
* ``muted``         → never

A direct @mention emails immediately unless the channel is muted. Members
with no subscription row fall back to the channel's default level.

Mentions are matched by *directory slug* — the slugified "First Last" that
already identifies a member in directory URLs — so ``@mona-member`` resolves
to that member.
"""

from __future__ import annotations

import re

from django.contrib.auth import get_user_model

from notifications.categories import Category
from notifications.dispatch import notify

from . import emails
from .models import Subscription, SubscriptionLevel
from .permissions import channel_visible

User = get_user_model()

_MENTION_RE = re.compile(r"@([a-z0-9][a-z0-9._-]*)", re.IGNORECASE)
_Level = SubscriptionLevel


def _actor_name(user) -> str:
    return (user.get_full_name() if user else "") or "Someone"


def _post_url(post) -> str:
    """Where a notification about ``post`` should land."""
    if post.thread_id:
        return f"{post.thread.get_absolute_url()}#post-{post.id}"
    return post.channel.get_absolute_url()


def _mentioned_users(body: str, channel) -> list:
    """Members named with @slug in ``body`` who can see ``channel``."""
    tokens = {t.lower() for t in _MENTION_RE.findall(body or "")}
    if not tokens:
        return []
    found = []
    for user in User.objects.select_related("profile"):
        profile = getattr(user, "profile", None)
        if profile is None:
            continue
        if profile.directory_slug.lower() in tokens and channel_visible(channel, user):
            found.append(user)
    return found


def _channel_levels(channel) -> dict[int, str]:
    """Map of user_id → subscription level for ``channel`` (rows that exist)."""
    return {
        s.user_id: s.level
        for s in Subscription.objects.filter(channel=channel)
    }


def _effective_level(levels: dict[int, str], channel, user_id: int) -> str:
    return levels.get(user_id, channel.default_subscription_level)


def notify_post(post) -> None:
    """Notifications + immediate emails for a new reply or chat post."""
    if post.channel.is_ephemeral:
        return  # disappearing chats are in-the-moment — no notifications/emails
    actor_id = post.author_id
    channel = post.channel
    thread = post.thread
    levels = _channel_levels(channel)
    emailed: set[int] = set()
    mentioned_ids = set()

    actor_name = _actor_name(post.author)
    url = _post_url(post)
    for user in _mentioned_users(post.body, channel):
        if user.id == actor_id:
            continue
        notify(
            user, Category.PARLETRE_MENTION, actor=post.author,
            title=f"{actor_name} mentioned you",
            body=(thread.title if thread else f"#{channel.slug}"),
            url=url, target=post, email=False,
        )
        mentioned_ids.add(user.id)
        if _effective_level(levels, channel, user.id) != _Level.MUTED:
            emails.send_post_notification(post, user, "mention")
            emailed.add(user.id)

    if (
        thread is not None
        and thread.author_id
        and thread.author_id != actor_id
        and thread.author_id not in mentioned_ids
    ):
        notify(
            thread.author, Category.PARLETRE_REPLY, actor=post.author,
            title=f"{actor_name} replied in your thread",
            body=thread.title, url=url, target=post, email=False,
        )

    # Email everyone who wants every post.
    for sub in Subscription.objects.filter(
        channel=channel, level=_Level.ALL
    ).exclude(user_id=actor_id).select_related("user"):
        if sub.user_id in emailed:
            continue
        emails.send_post_notification(post, sub.user, "post")
        emailed.add(sub.user_id)


def notify_new_thread(thread, first_post) -> None:
    """Notifications + immediate emails for a new thread."""
    if thread.channel.is_ephemeral:
        return
    actor_id = thread.author_id
    channel = thread.channel
    levels = _channel_levels(channel)
    emailed: set[int] = set()
    mentioned_ids = set()

    actor_name = _actor_name(thread.author)
    thread_url = thread.get_absolute_url()
    for user in _mentioned_users(first_post.body, channel):
        if user.id == actor_id:
            continue
        notify(
            user, Category.PARLETRE_MENTION, actor=thread.author,
            title=f"{actor_name} mentioned you",
            body=thread.title, url=f"{thread_url}#post-{first_post.id}",
            target=first_post, email=False,
        )
        mentioned_ids.add(user.id)
        if _effective_level(levels, channel, user.id) != _Level.MUTED:
            emails.send_post_notification(first_post, user, "mention")
            emailed.add(user.id)

    followers = (
        Subscription.objects.filter(
            channel=channel,
            level__in=(_Level.ALL, _Level.THREADS_ONLY),
        )
        .exclude(user_id=actor_id)
        .select_related("user", "user__profile")
    )
    for sub in followers:
        if sub.user_id in mentioned_ids:
            continue
        if not channel_visible(channel, sub.user):
            continue
        notify(
            sub.user, Category.PARLETRE_THREAD, actor=thread.author,
            title=f"{actor_name} started a thread",
            body=thread.title, url=thread_url, target=thread, email=False,
        )
        if sub.user_id not in emailed:
            emails.send_post_notification(first_post, sub.user, "new_thread")
            emailed.add(sub.user_id)
