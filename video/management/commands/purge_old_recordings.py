"""Delete recordings past the retention window (default 1 year) unless marked
`keep`. Removes the S3 object (owned-S3 mode) + the Daily recording + marks the
row DELETED. Run by a host systemd timer. Mirrors purge_expired_messages.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from video import daily
from video.models import Recording


class Command(BaseCommand):
    help = "Delete recordings older than RECORDING_RETENTION_DAYS (unless kept)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        days = getattr(settings, "RECORDING_RETENTION_DAYS", 365)
        cutoff = timezone.now() - timedelta(days=days)
        stale = Recording.objects.filter(created_at__lt=cutoff, keep=False).exclude(
            status=Recording.Status.DELETED
        )
        n = 0
        for rec in stale:
            if opts["dry_run"]:
                self.stdout.write(f"[dry-run] would delete: {rec.title or rec.daily_recording_id}")
                continue
            if rec.s3_key:
                try:
                    from core.storage import recordings_storage
                    recordings_storage().delete(rec.s3_key)
                except Exception as exc:  # noqa: BLE001
                    self.stderr.write(f"  S3 delete failed for {rec.pk}: {exc}")
            try:
                daily.delete_recording(rec.daily_recording_id)
            except daily.DailyError as exc:
                self.stderr.write(f"  Daily delete failed for {rec.pk}: {exc}")
            rec.status = Recording.Status.DELETED
            rec.s3_key = ""
            rec.save(update_fields=["status", "s3_key"])
            n += 1
        self.stdout.write(self.style.SUCCESS(f"Purged {n} recording(s) (> {days} days)."))
