"""Bulk-geocode ``Profile.location`` strings.

For each profile, splits the location string into one or more sub-places
(see accounts.geocoding.split_location), geocodes each, stores all
results in ``Profile.location_pins`` as a list of {lat,lng,label} dicts,
and writes the primary coord (first hit) to ``location_lat`` / ``location_lng``
for backward compatibility.

Idempotent: skips profiles that already have coords unless ``--force``.
Respects Nominatim's 1 req/sec rate limit via geopy RateLimiter.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.geocoding import make_batch_geocoder, split_location
from accounts.models import Profile


class Command(BaseCommand):
    help = "Geocode Profile.location into location_lat/lng + location_pins."

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
                pieces = split_location(p.location)
                pins: list[dict] = []
                for piece in pieces:
                    result = geocode(piece)
                    if result is None:
                        self.stderr.write(self.style.WARNING(
                            f"  miss: {p.user.first_name} {p.user.last_name} "
                            f"({piece!r})"
                        ))
                        continue
                    pins.append({
                        "lat":   result.lat,
                        "lng":   result.lng,
                        "label": piece,
                    })

                if not pins:
                    misses += 1
                    continue

                pin_descr = ", ".join(
                    f"{pin['label']}→({pin['lat']:.4f},{pin['lng']:.4f})"
                    for pin in pins
                )
                self.stdout.write(
                    f"  {p.user.first_name} {p.user.last_name}: {pin_descr}"
                )

                p.location_pins = pins
                # Keep primary lat/lng pointing at the first pin for any code
                # that hasn't moved to location_pins yet.
                p.location_lat = pins[0]["lat"]
                p.location_lng = pins[0]["lng"]
                p.save(update_fields=["location_pins", "location_lat", "location_lng"])
                hits += 1

            if dry_run:
                transaction.set_rollback(True)

        prefix = "Would " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}geocode {hits} profiles, miss {misses} of {len(targets)}."
        ))
