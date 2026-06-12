"""Daily referral housekeeping. Wire via a daily systemd timer on the host.

Two jobs:

* When the follow-up step is set to *automatic*, send the assembled
  follow-up for any distributed request whose response window has closed.
* Privacy retention: redact identifying details on requests replied/closed
  longer ago than the retention window (always on — this is the
  auto-archive/purge the requester was promised).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from referrals import services
from referrals.models import Mode, ReferralRequest, ReferralSettings


class Command(BaseCommand):
    help = "Send due automatic follow-ups and redact expired referral requests."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would happen without sending or redacting.",
        )

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        config = ReferralSettings.load()
        now = timezone.now()

        sent = errored = 0
        if config.followup_mode == Mode.AUTO:
            due = ReferralRequest.objects.filter(
                status=ReferralRequest.Status.DISTRIBUTED,
                responses_due_at__lte=now,
            )
            for req in due:
                if dry:
                    self.stdout.write(f"  would send follow-up for {req.reference}")
                    sent += 1
                    continue
                try:
                    subject, body = services.build_followup(req)
                    services.send_followup(req, subject, body)
                    sent += 1
                except Exception as exc:
                    errored += 1
                    self.stderr.write(f"  failed for {req.reference}: {exc}")

        if dry:
            # Count without mutating.
            purged = sum(
                1 for _ in ReferralRequest.objects.filter(
                    purged_at__isnull=True,
                    status__in=(
                        ReferralRequest.Status.REPLIED,
                        ReferralRequest.Status.CLOSED,
                    ),
                )
            )
            self.stdout.write(
                f"Would send {sent} follow-up(s); up to {purged} request(s) "
                "eligible for redaction check."
            )
            return

        purged = services.purge_expired(now)
        self.stdout.write(self.style.SUCCESS(
            f"Sent {sent} follow-up(s), redacted {purged} request(s). "
            f"Errors: {errored}."
        ))
