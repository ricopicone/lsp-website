"""Re-ingest recordings Daily has but the site missed (task #475).

Recording rows are created only by the Daily webhook, so a failed delivery is
unrecoverable without this: the file sits in our bucket with no row pointing at
it. Mirrors ``reconcile_stripe_pending``, which exists for the same reason on
the payments side.

Safe to re-run — it only touches recordings Daily reports as ``finished`` that
we have no READY row for, and never resurrects a deliberately purged one.
Meant for a daily host timer::

    uv run python manage.py reconcile_daily_recordings
    uv run python manage.py reconcile_daily_recordings --dry-run
    uv run python manage.py reconcile_daily_recordings --room lsp-event-working-with-masochism
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from video import daily, services


class Command(BaseCommand):
    help = "Recover recordings Daily has that never reached the site via webhook."

    def add_arguments(self, parser):
        parser.add_argument(
            "--room", default=None,
            help="Only reconcile recordings in this Daily room name.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be ingested without writing.",
        )

    def handle(self, *args, **opts):
        if not services.daily_enabled():
            self.stdout.write("Daily is not enabled; nothing to reconcile.")
            return
        try:
            created, updated, skipped = services.reconcile_recordings(
                room_name=opts["room"], dry_run=opts["dry_run"],
            )
        except daily.DailyError as exc:
            self.stderr.write(self.style.ERROR(f"Daily API error: {exc}"))
            return

        prefix = "[dry-run] would ingest" if opts["dry_run"] else "Ingested"
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix} {created} new recording(s), repaired {updated}, "
                f"skipped {skipped} already-known or unfinished."
            )
        )
