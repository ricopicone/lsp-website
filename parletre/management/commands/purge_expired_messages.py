"""Redact expired messages in disappearing channels (e.g. Purloined Letters).

Run frequently via a systemd timer (lsp-parletre-purge.timer). For each
message past its channel's TTL, the real text and attachment files are
permanently deleted, but a blacked-out bar (██ ████) stays in place — the
content is gone, the redaction remains. The chat view also redacts on read,
so there's no content-leak window between expiry and this run.

(Command name kept as ``purge_expired_messages`` so the existing host timer
needs no change, even though it now redacts rather than removes the row.)
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from parletre.models import Channel, Post, blackout


class Command(BaseCommand):
    help = "Redact (black out) messages older than their channel's message_ttl_seconds."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be redacted without changing anything.",
        )

    def handle(self, *args, **opts):
        now = timezone.now()
        total = 0
        for channel in Channel.objects.filter(message_ttl_seconds__isnull=False):
            cutoff = now - timedelta(seconds=channel.message_ttl_seconds)
            expired = Post.objects.filter(
                channel=channel, created_at__lt=cutoff, redacted=False
            )
            count = expired.count()
            if not count:
                continue
            if opts["dry_run"]:
                self.stdout.write(f"[dry-run] #{channel.slug}: would redact {count}")
                continue
            for post in expired.prefetch_related("attachments"):
                post.body = blackout(post.body)
                post.redacted = True
                post.save(update_fields=["body", "redacted"])
                for att in post.attachments.all():
                    try:
                        att.file.delete(save=True)  # remove the real file; keep the row
                    except Exception:  # noqa: BLE001 — best-effort file removal
                        pass
            total += count
        self.stdout.write(self.style.SUCCESS(f"Redacted {total} expired message(s)."))
