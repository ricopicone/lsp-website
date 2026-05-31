"""Seed Parlêtre with starter categories and channels.

Idempotent (get_or_create by slug), so it's safe to re-run. Per-committee /
per-workgroup channels are NOT seeded here — they're auto-provisioned when the
workgroup is created (see ``parletre/signals.py``).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

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

        # Disappearing-message chat — the letter that does not arrive.
        _, was_created = Channel.objects.get_or_create(
            slug="purloined-letters",
            defaults={
                "name": "Purloined Letters",
                "category": cats.get("general"),
                "kind": Channel.Kind.CHAT,
                "access": Channel.Access.OPEN,
                "message_ttl_seconds": 86400,  # 24h; admin-configurable
                "description": "A disappearing chat — messages vanish 24 hours "
                "after posting. Say it while it lasts.",
            },
        )
        created += was_created

        self.stdout.write(
            self.style.SUCCESS(f"Parlêtre seeded ({created} new channel(s)).")
        )
