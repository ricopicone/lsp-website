"""Weekly reminder to interviewers who haven't reported yet.

For every agreed-but-incomplete application interview whose last reminder was
more than a week ago (or never), email the interviewer to set up the meeting
and submit their report. Wire as a weekly host timer at launch (member-facing
— keep off until then). ``--dry-run`` reports only.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from admissions import notifications as notify_admissions
from admissions.models import Application, ApplicationInterview


class Command(BaseCommand):
    help = "Email interviewers with outstanding reports a weekly reminder."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(days=7)
        interviews = (
            ApplicationInterview.objects.filter(
                application__status=Application.Status.INTERVIEWING,
            )
            .select_related("application__applicant", "interviewer")
        )
        sent = 0
        for iv in interviews:
            if iv.is_complete:
                continue
            if iv.last_reminded_at and iv.last_reminded_at > cutoff:
                continue
            who = iv.interviewer.get_full_name() or iv.interviewer.email
            applicant = (
                iv.application.applicant.get_full_name()
                or iv.application.applicant.email
            )
            self.stdout.write(f"  remind {who} re {applicant}")
            if not opts["dry_run"]:
                notify_admissions.interview_reminder(iv)
                iv.last_reminded_at = timezone.now()
                iv.save(update_fields=["last_reminded_at"])
            sent += 1

        verb = "Would remind" if opts["dry_run"] else "Reminded"
        self.stdout.write(self.style.SUCCESS(f"{verb} {sent} interviewer(s)."))
