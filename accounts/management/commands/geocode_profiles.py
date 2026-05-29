"""Bulk-geocode ``Profile.location`` strings into ``location_lat`` / ``location_lng``.

Idempotent: skips profiles that already have coords unless ``--force`` is set.
Respects Nominatim's 1 req/sec rate limit via geopy RateLimiter.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.geocoding import make_batch_geocoder
from accounts.models import Profile


class Command(BaseCommand):
    help = "Geocode Profile.location strings into lat/lng (Nominatim, polite)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-geocode profiles that already have coords.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Process at most N profiles (useful for testing).",
        )

    def handle(self, *args, force: bool, dry_run: bool, limit, **opts):
        qs = (
            Profile.objects
            .exclude(location="")
            .order_by("user__last_name", "user__first_name")
        )
        if not force:
            qs = qs.filter(location_lat__isnull=True)
        if limit:
            qs = qs[:limit]

        targets = list(qs.select_related("user"))
        self.stdout.write(f"Geocoding {len(targets)} profiles…")

        geocode = make_batch_geocoder(per_request_delay=1.1)

        hits = misses = 0

        with transaction.atomic():
            for p in targets:
                result = geocode(p.location)
                if result is None:
                    misses += 1
                    self.stderr.write(self.style.WARNING(
                        f"  miss: {p.user.first_name} {p.user.last_name} "
                        f"({p.location!r})"
                    ))
                    continue
                self.stdout.write(
                    f"  {p.user.first_name} {p.user.last_name}: "
                    f"{p.location!r} → ({result.lat:.4f}, {result.lng:.4f}) "
                    f"[{result.formatted[:60]}…]"
                )
                p.location_lat = result.lat
                p.location_lng = result.lng
                p.save(update_fields=["location_lat", "location_lng"])
                hits += 1

            if dry_run:
                transaction.set_rollback(True)

        prefix = "Would " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}geocoded {hits}, missed {misses} of {len(targets)}."
        ))
