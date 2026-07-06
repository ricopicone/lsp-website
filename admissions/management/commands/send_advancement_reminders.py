"""Remind Advisors to present formation demandes to the Meeting of the Analysts.

For every advancement still in REQUESTED status (the Advisor has not yet
presented it), nudge the Advisor — at most once per ``--interval`` days,
throttled via the demande's ``last_reminded_at``. Reminders stop automatically
once the Advisor marks the demande presented (status → PRESENTED).

Like the dues/tuition reminders, this is a member-facing cron: keep it disabled
until launch.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from formation import notifications as notify_formation
from formation.models import Advancement


class Command(BaseCommand):
    help = "Remind Advisors to present open formation demandes to the Meeting."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval", type=int, default=7,
            help="Minimum days between reminders for the same demande (default 7).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be sent without sending or logging.",
        )

    def handle(self, *args, **opts):
        now = timezone.now()
        cutoff = now - timedelta(days=opts["interval"])
        due = (
            Advancement.objects.filter(
                status=Advancement.Status.REQUESTED, advisor__isnull=False,
            )
            .filter(models_q_due(cutoff))
            .select_related("member", "advisor")
        )
        sent = 0
        for adv in due:
            who = adv.advisor.email
            member = adv.member.get_full_name() or adv.member.email
            if opts["dry_run"]:
                self.stdout.write(f"[dry-run] would remind {who} re {member}")
                continue
            try:
                notify_formation.advancement_reminder(adv)
            except Exception:
                self.stderr.write(f"failed to remind {who} re {member}")
                continue
            adv.last_reminded_at = now
            adv.save(update_fields=["last_reminded_at"])
            sent += 1
        self.stdout.write(self.style.SUCCESS(
            f"{'Would send' if opts['dry_run'] else 'Sent'} "
            f"{due.count() if opts['dry_run'] else sent} advancement reminder(s)."
        ))


def models_q_due(cutoff):
    from django.db.models import Q
    return Q(last_reminded_at__isnull=True) | Q(last_reminded_at__lte=cutoff)
