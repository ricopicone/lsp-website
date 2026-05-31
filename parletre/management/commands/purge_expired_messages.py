"""Hard-delete expired messages in disappearing channels (e.g. Purloined Letters).

Run frequently via a systemd timer (every few minutes). The chat view already
*hides* messages past their channel's TTL; this command permanently removes
them from the database so they truly disappear (attachments and reactions
cascade; replies to a purged message keep working via reply_to=SET_NULL).
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from parletre.models import Channel, Post


class Command(BaseCommand):
    help = "Permanently delete messages older than their channel's message_ttl_seconds."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be purged without deleting.",
        )

    def handle(self, *args, **opts):
        now = timezone.now()
        total = 0
        for channel in Channel.objects.filter(message_ttl_seconds__isnull=False):
            cutoff = now - timedelta(seconds=channel.message_ttl_seconds)
            expired = Post.objects.filter(channel=channel, created_at__lt=cutoff)
            count = expired.count()
            if not count:
                continue
            if opts["dry_run"]:
                self.stdout.write(f"[dry-run] #{channel.slug}: would purge {count}")
                continue
            expired.delete()
            total += count
        self.stdout.write(self.style.SUCCESS(f"Purged {total} expired message(s)."))
