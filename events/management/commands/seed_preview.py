"""Seed everything the limited-preview onboarding tour points at:

  * the sandbox **Preview Seminar** — published, open, with a single $0 price
    tier, so registering skips Stripe and lands straight at PAID; and
  * an open **Welcome** Parlêtre chat channel for the "say hello" task.

Idempotent (keyed on the configured slugs), safe to re-run. The tour itself
stays invisible until ``DJANGO_PREVIEW_TOUR_ENABLED=true`` — this only creates
the content it links to.

    manage.py seed_preview
    manage.py seed_preview --members-only   # keep the seminar off public lists
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import Audience, Event, PriceTier
from parletre.models import Channel, ChannelCategory, SubscriptionLevel


class Command(BaseCommand):
    help = "Create/update the preview sandbox seminar + Welcome channel."

    def add_arguments(self, parser):
        parser.add_argument(
            "--members-only",
            action="store_true",
            help="Set the seminar's visibility to members-only (off the public list).",
        )

    def handle(self, *args, **options):
        self._seed_seminar(members_only=options["members_only"])
        self._seed_welcome_channel()

    def _seed_seminar(self, *, members_only: bool):
        slug = getattr(settings, "PREVIEW_TOUR_SEMINAR_SLUG", "preview-seminar")
        today = timezone.now().date()
        visibility = (
            Event.Visibility.MEMBERS_ONLY if members_only else Event.Visibility.PUBLIC
        )

        event, created = Event.objects.update_or_create(
            slug=slug,
            defaults={
                "title": "Preview Seminar",
                "description": (
                    "A sandbox seminar for the limited preview. Registration is "
                    "free and instant — no payment, no real commitment — so you "
                    "can try the full sign-up flow end to end. Feel free to "
                    "register and then cancel."
                ),
                "event_type": Event.Type.SEMINAR,
                "format": Event.Format.ONLINE,
                "start_date": today + timedelta(days=14),
                "end_date": today + timedelta(days=120),
                "status": Event.Status.OPEN,
                "published": True,
                "visibility": visibility,
                "access_info": (
                    "This is a preview sandbox event — there's no real meeting. "
                    "On the live site, your Zoom link and materials would appear "
                    "here once you're registered."
                ),
            },
        )
        # One free tier for everyone → $0 → registration short-circuits to PAID.
        PriceTier.objects.update_or_create(
            event=event,
            audience=Audience.ALL,
            session=None,
            defaults={
                "base_amount": Decimal("0.00"),
                "sliding_scale": False,
                "covered_by_tuition": False,
            },
        )
        verb = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} Preview Seminar (slug={event.slug}, visibility={event.visibility}) "
            f"with a $0 tier."
        ))

    def _seed_welcome_channel(self):
        slug = getattr(settings, "PREVIEW_TOUR_CHANNEL_SLUG", "welcome")
        category, _ = ChannelCategory.objects.get_or_create(
            slug="general", defaults={"name": "General", "position": 0}
        )
        channel, created = Channel.objects.update_or_create(
            slug=slug,
            defaults={
                "name": "Welcome",
                "category": category,
                "kind": Channel.Kind.CHAT,
                "access": Channel.Access.OPEN,
                "post_policy": Channel.PostPolicy.OPEN,
                "auto_subscribe": True,
                "default_subscription_level": SubscriptionLevel.ALL,
                "description": "Say hello and meet the other preview members.",
            },
        )
        verb = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} Welcome channel (slug={channel.slug}, access={channel.access})."
        ))
