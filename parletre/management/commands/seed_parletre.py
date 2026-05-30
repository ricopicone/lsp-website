"""Seed Parlêtre with starter categories and channels.

Idempotent (get_or_create by slug), so it's safe to re-run. Committee
channels are only created if the matching committee exists (the committees
app seeds Board / Programming Committee / LSP Staff).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from committees.models import Committee
from parletre.models import Channel, ChannelCategory, SubscriptionLevel

CATEGORIES = [
    ("General", "general", 0),
    ("Committees", "committees", 10),
    ("Cartels", "cartels", 20),
]

# (slug, name, category_slug, kind, access, post_policy, auto_subscribe, description)
CHANNELS = [
    (
        "announcements", "Announcements", "general",
        Channel.Kind.FORUM, Channel.Access.OPEN, Channel.PostPolicy.STAFF_ONLY, True,
        "School-wide announcements. Everyone is subscribed; only staff post.",
    ),
    (
        "commons", "The Commons", "general",
        Channel.Kind.FORUM, Channel.Access.OPEN, Channel.PostPolicy.OPEN, False,
        "Open discussion for all members of the school.",
    ),
    (
        "lounge", "The Lounge", "general",
        Channel.Kind.CHAT, Channel.Access.OPEN, Channel.PostPolicy.OPEN, False,
        "Casual chat.",
    ),
]

# (slug, name, committee_slug, description)
COMMITTEE_CHANNELS = [
    ("board", "Board", "board", "Private channel for the Board."),
    (
        "programming-committee", "Programming Committee", "programming-committee",
        "Private channel for the Programming Committee.",
    ),
]


class Command(BaseCommand):
    help = "Create starter Parlêtre categories and channels (idempotent)."

    def handle(self, *args, **opts):
        cats = {}
        for name, slug, position in CATEGORIES:
            cat, _ = ChannelCategory.objects.get_or_create(
                slug=slug, defaults={"name": name, "position": position}
            )
            cats[slug] = cat

        created = 0
        for slug, name, cat_slug, kind, access, policy, auto_sub, desc in CHANNELS:
            level = SubscriptionLevel.ALL if auto_sub else SubscriptionLevel.DIGEST
            _, was_created = Channel.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "category": cats.get(cat_slug),
                    "kind": kind,
                    "access": access,
                    "post_policy": policy,
                    "auto_subscribe": auto_sub,
                    "default_subscription_level": level,
                    "description": desc,
                },
            )
            created += was_created

        for slug, name, committee_slug, desc in COMMITTEE_CHANNELS:
            committee = Committee.objects.filter(slug=committee_slug).first()
            if committee is None:
                self.stdout.write(f"  (skipped {slug}: no '{committee_slug}' committee)")
                continue
            _, was_created = Channel.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "category": cats.get("committees"),
                    "kind": Channel.Kind.FORUM,
                    "access": Channel.Access.COMMITTEE,
                    "committee": committee,
                    "description": desc,
                },
            )
            created += was_created

        self.stdout.write(
            self.style.SUCCESS(f"Parlêtre seeded ({created} new channel(s)).")
        )
