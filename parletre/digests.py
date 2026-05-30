"""Building the periodic email digest (DISC-6).

A member's digest gathers posts since their last digest in the channels they
follow at *digest* level (the quiet default), grouped by thread, excluding
their own posts. Channels they follow louder (all / threads) are emailed
immediately instead and don't appear here.
"""

from __future__ import annotations

from collections import OrderedDict

from django.conf import settings

from .models import Post, Subscription, SubscriptionLevel
from .permissions import channel_visible


def _abs(path: str) -> str:
    return f"{settings.SITE_BASE_URL.rstrip('/')}{path}"


def build_sections(user, since) -> list[dict]:
    """Digest sections for ``user`` covering activity after ``since``.

    Returns ``[{"channel", "groups": [{"label", "url", "posts"}]}]`` — empty
    when there's nothing new.
    """
    sections = []
    subs = (
        Subscription.objects.filter(user=user, level=SubscriptionLevel.DIGEST)
        .select_related("channel", "channel__committee", "channel__category")
        .order_by("channel__category__position", "channel__position")
    )
    for sub in subs:
        channel = sub.channel
        if not channel_visible(channel, user):
            continue
        posts = list(
            Post.objects.filter(channel=channel, created_at__gt=since, deleted=False)
            .exclude(author_id=user.id)
            .select_related("thread", "author")
            .order_by("created_at")
        )
        if not posts:
            continue
        groups: OrderedDict = OrderedDict()
        for post in posts:
            if post.thread_id:
                key = ("t", post.thread_id)
                label = post.thread.title
                url = _abs(post.thread.get_absolute_url())
            else:
                key = ("c", channel.id)
                label = "Chat"
                url = _abs(channel.get_absolute_url())
            group = groups.setdefault(key, {"label": label, "url": url, "posts": []})
            group["posts"].append(post)
        sections.append({"channel": channel, "groups": list(groups.values())})
    return sections
