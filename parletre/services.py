"""Side-effects of posting in Parlêtre: @mention parsing and in-app
notifications (the nav bell).

Mentions are matched by *directory slug* — the slugified "First Last" that
already identifies a member in directory URLs — so ``@mona-member`` resolves
to that member. A picker/autocomplete that inserts the right token is a later
(JS) polish; the resolution and notification plumbing live here.
"""

from __future__ import annotations

import re

from django.contrib.auth import get_user_model

from .models import Notification, Subscription, SubscriptionLevel
from .permissions import channel_visible

User = get_user_model()

#: @token where token looks like a directory slug (letters, digits, - . _).
_MENTION_RE = re.compile(r"@([a-z0-9][a-z0-9._-]*)", re.IGNORECASE)


def _mentioned_users(body: str, channel) -> list:
    """Members named with @slug in ``body`` who can see ``channel``.

    Matches each @token against members' directory slugs. Iterates members
    (a property, not a DB column, so it can't be queried) — fine at the
    school's scale (~100s). Returns [] fast when there are no @tokens.
    """
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


def notify_post(post) -> None:
    """Notifications for a new reply or chat post: @mentions, then a reply
    notice to the thread's author."""
    actor_id = post.author_id
    mentioned_ids = set()
    for user in _mentioned_users(post.body, post.channel):
        if user.id == actor_id:
            continue
        Notification.objects.create(
            recipient=user,
            actor=post.author,
            verb=Notification.Verb.MENTION,
            post=post,
            thread=post.thread,
        )
        mentioned_ids.add(user.id)

    thread = post.thread
    if (
        thread is not None
        and thread.author_id
        and thread.author_id != actor_id
        and thread.author_id not in mentioned_ids
    ):
        Notification.objects.create(
            recipient_id=thread.author_id,
            actor=post.author,
            verb=Notification.Verb.REPLY,
            post=post,
            thread=thread,
        )


def notify_new_thread(thread, first_post) -> None:
    """Notifications for a new thread: @mentions in the opening post, then a
    new-thread notice to members who follow the channel closely."""
    actor_id = thread.author_id
    channel = thread.channel
    mentioned_ids = set()
    for user in _mentioned_users(first_post.body, channel):
        if user.id == actor_id:
            continue
        Notification.objects.create(
            recipient=user,
            actor=thread.author,
            verb=Notification.Verb.MENTION,
            post=first_post,
            thread=thread,
        )
        mentioned_ids.add(user.id)

    followers = (
        Subscription.objects.filter(
            channel=channel,
            level__in=(SubscriptionLevel.ALL, SubscriptionLevel.THREADS_ONLY),
        )
        .exclude(user_id=actor_id)
        .select_related("user", "user__profile")
    )
    for sub in followers:
        if sub.user_id in mentioned_ids:
            continue
        if not channel_visible(channel, sub.user):
            continue
        Notification.objects.create(
            recipient=sub.user,
            actor=thread.author,
            verb=Notification.Verb.NEW_THREAD,
            thread=thread,
        )
