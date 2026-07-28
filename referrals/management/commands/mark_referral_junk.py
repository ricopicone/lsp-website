"""Mark a referral request as junk from the command line.

Exists for the prod cleanup of 26-0727 (task #479), which predates the
JUNK status. The coordinator's normal route is the button on the request
page; this is for one-off staff work over SSM where no browser is handy.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from referrals.models import ReferralRequest


class Command(BaseCommand):
    help = "Mark a referral request as junk, with an audit note."

    def add_arguments(self, parser):
        parser.add_argument("reference", help="e.g. 26-0727")
        parser.add_argument(
            "--note", default="Marked as junk",
            help="Text appended to the coordinator notes.",
        )

    def handle(self, *args, **opts):
        try:
            req = ReferralRequest.objects.get(reference=opts["reference"])
        except ReferralRequest.DoesNotExist:
            raise CommandError(f"No referral request {opts['reference']!r}.")

        stamp = timezone.now().strftime("%Y-%m-%d %H:%M")
        line = f"[{stamp}] {opts['note']} — manage.py mark_referral_junk"
        req.coordinator_notes = (
            f"{req.coordinator_notes}\n{line}".strip()
            if req.coordinator_notes else line
        )
        req.status = ReferralRequest.Status.JUNK
        req.save(update_fields=["status", "coordinator_notes"])
        self.stdout.write(self.style.SUCCESS(
            f"{req.reference} marked as junk."
        ))
