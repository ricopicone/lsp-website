"""Daily referral housekeeping. Wire via a daily systemd timer on the host.

Two jobs:

* When the follow-up step is set to *automatic*, send the assembled
  follow-up for any distributed request whose response window has closed.
* Privacy retention: redact identifying details on requests replied/closed
  longer ago than the retention window (always on — this is the
  auto-archive/purge the requester was promised).
* Escalate any submission held by the spam screen that has sat unreviewed
  past ``held_escalation_days``, and prune expired blocked-submission
  counter rows (task #479).
"""

from __future__ import annotations

from datetime import timedelta

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
            stale_holds = ReferralRequest.objects.filter(
                status=ReferralRequest.Status.HELD,
                held_at__lte=now - timedelta(days=config.held_escalation_days),
                held_escalated_at__isnull=True,
            ).count()
            self.stdout.write(
                f"Would send {sent} follow-up(s); up to {purged} request(s) "
                f"eligible for redaction check; would escalate "
                f"{stale_holds} held request(s)."
            )
            return

        purged = services.purge_expired(now)
        escalated = services.escalate_stale_holds(now)
        pruned = services.prune_blocked_submissions(now)
        self.stdout.write(self.style.SUCCESS(
            f"Sent {sent} follow-up(s), redacted {purged} request(s), "
            f"escalated {escalated} held request(s), pruned {pruned} "
            f"blocked-submission row(s). Errors: {errored}."
        ))
