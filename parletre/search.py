"""Search across Parlêtre posts (DISC-4).

Full-text search via Postgres (``SearchVector``/``SearchQuery``) in
production; a plain ``icontains`` fallback on SQLite (dev/tests). Results are
scoped to the channels the searching member can actually see — you can't
find your way into a private channel through search.
"""

from __future__ import annotations

import re

from django.db import connection
from django.db.models import Q
from django.utils.html import escape
from django.utils.safestring import mark_safe

from .models import Channel, Post
from .permissions import channel_visible


def visible_channel_ids(user) -> list[int]:
    channels = (
        Channel.objects.select_related("committee")
        .prefetch_related("members", "moderators")
    )
    return [c.id for c in channels if channel_visible(c, user)]


def search_posts(user, query: str, *, limit: int = 50):
    """Posts (body or thread title matching ``query``) the member may see."""
    query = (query or "").strip()
    if not query:
        return []
    channel_ids = visible_channel_ids(user)
    if not channel_ids:
        return []
    qs = Post.objects.filter(
        channel_id__in=channel_ids, deleted=False, channel__message_ttl_seconds__isnull=True
    ).select_related("author", "thread", "channel")
    if connection.vendor == "postgresql":
        from django.contrib.postgres.search import (
            SearchQuery,
            SearchRank,
            SearchVector,
        )

        vector = SearchVector("body", "thread__title")
        search_query = SearchQuery(query, search_type="websearch")
        qs = (
            qs.annotate(rank=SearchRank(vector, search_query))
            .filter(rank__gt=0)
            .order_by("-rank", "-created_at")
        )
    else:
        qs = qs.filter(
            Q(body__icontains=query) | Q(thread__title__icontains=query)
        ).order_by("-created_at")
    return list(qs[:limit])


def make_snippet(body: str, query: str, *, width: int = 240) -> str:
    """A short, HTML-safe excerpt of ``body`` with the query term highlighted."""
    text = (body or "").strip()
    low, q_low = text.lower(), query.lower()
    idx = low.find(q_low) if query else -1
    if idx > 60:
        text = "…" + text[idx - 50:]
    snippet = text[:width] + ("…" if len(text) > width else "")
    out = escape(snippet)
    if query:
        pattern = re.compile(re.escape(escape(query)), re.IGNORECASE)
        out = pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", out)
    return mark_safe(out)
