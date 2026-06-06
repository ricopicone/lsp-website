"""Send the periodic notification digest to members who are due.

Run daily from a host timer. Daily-cadence members get a digest each run;
weekly-cadence members get one once their week has elapsed. Email is paced
through the shared :class:`~payments.sending.ThrottledSender` so a large batch
stays under the SES send rate. Idempotent within a cadence window: held items
are cleared once emailed, so a second same-day run sends nothing.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from notifications import digests
from notifications.models import NotificationPreference
from payments.sending import ThrottledSender


class Command(BaseCommand):
    help = "Email held notifications to members as a daily/weekly digest."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be sent without sending or stamping.",
        )

    def handle(self, *args, **opts):
        now = timezone.now()
        dry = opts["dry_run"]
        sender = ThrottledSender()
        sent = skipped_not_due = empty = errored = 0

        prefs = (
            NotificationPreference.objects.exclude(digest_cadence="off")
            .select_related("user")
        )
        for pref in prefs:
            if not digests.is_due(pref, now):
                skipped_not_due += 1
                continue
            items = digests.pending_for(pref.user)
            if not items:
                # Nothing held, but advance the watermark so we don't re-check
                # an idle member every run.
                empty += 1
                if not dry:
                    pref.last_digest_at = now
                    pref.save(update_fields=["last_digest_at"])
                continue
            if dry:
                self.stdout.write(f"  would send {len(items)} to {pref.user.email}")
                sent += 1
                continue
            try:
                sender.send(digests.send_digest, pref.user, items)
                digests.clear_pending(items, now)
                pref.last_digest_at = now
                pref.save(update_fields=["last_digest_at"])
                sent += 1
            except Exception as exc:
                errored += 1
                self.stderr.write(f"  failed for {pref.user.email}: {exc}")

        verb = "Would send" if dry else "Sent"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {sent} digest(s). Skipped {skipped_not_due} not due, "
            f"{empty} with nothing held. Errors: {errored}."
        ))
