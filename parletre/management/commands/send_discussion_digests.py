"""Send Parlêtre email digests (DISC-6).

Run daily via a systemd timer on the EC2 host (mirrors lsp-dues-cron). Each
run sends a digest to every member whose cadence is due: daily members every
day, weekly members once their week has elapsed. The watermark
(``DigestPreference.last_sent_at``) gates both cadence and the window of
posts included, so a missed run just folds into the next.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from parletre.digests import build_sections
from parletre.emails import send_digest
from parletre.models import DigestPreference

_INTERVAL = {
    DigestPreference.Frequency.DAILY: timedelta(days=1),
    DigestPreference.Frequency.WEEKLY: timedelta(days=7),
}
_LABEL = {
    DigestPreference.Frequency.DAILY: "Daily",
    DigestPreference.Frequency.WEEKLY: "Weekly",
}


class Command(BaseCommand):
    help = "Send Parlêtre email digests to members on a daily/weekly cadence."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be sent without sending or updating watermarks.",
        )

    def handle(self, *args, **opts):
        dry_run = opts["dry_run"]
        now = timezone.now()
        sent = 0
        prefs = (
            DigestPreference.objects.exclude(frequency=DigestPreference.Frequency.OFF)
            .select_related("user")
        )
        for pref in prefs:
            interval = _INTERVAL[pref.frequency]
            # A small slack so a cron that fires slightly early still counts.
            if pref.last_sent_at and (now - pref.last_sent_at) < interval - timedelta(hours=1):
                continue
            since = pref.last_sent_at or (now - interval)
            sections = build_sections(pref.user, since)
            if not sections:
                continue
            label = _LABEL[pref.frequency]
            if dry_run:
                self.stdout.write(
                    f"[dry-run] {label} digest to {pref.user.email}: "
                    f"{len(sections)} channel(s)"
                )
                continue
            if send_digest(pref.user, sections, period_label=label):
                pref.last_sent_at = now
                pref.save(update_fields=["last_sent_at"])
                sent += 1

        self.stdout.write(self.style.SUCCESS(f"Sent {sent} digest(s)."))
