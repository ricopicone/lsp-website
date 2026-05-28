"""Send weekly dues reminders to obligated unpaid members (REG-12).

Wire via a weekly systemd timer on the EC2 host. Idempotent within a
7-day window via the ``DuesReminder`` log: a user who's already been
reminded in the last 7 days for the current period is skipped.

Skips:
- users not in ``DUES_OBLIGATED_ROLES``
- users who already paid for the current period
- users whose last reminder was within the past 7 days
- when no current period exists, or it's not yet past due date
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from payments.dues import is_dues_obligated, user_paid_for_period
from payments.emails import send_dues_reminder
from payments.models import DuesPeriod, DuesReminder

User = get_user_model()


class Command(BaseCommand):
    help = "Send weekly dues reminders to obligated unpaid users."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be sent without sending or logging.",
        )

    def handle(self, *args, **opts):
        period = DuesPeriod.current()
        if period is None:
            self.stdout.write("No current DuesPeriod; nothing to do.")
            return

        today = timezone.now().date()
        if today < period.due_date:
            self.stdout.write(
                f"Period {period.name} not yet past due ({period.due_date}); "
                "skipping reminders."
            )
            return

        week_ago = timezone.now() - timedelta(days=7)
        sent = 0
        skipped_paid = 0
        skipped_recent = 0
        skipped_not_obligated = 0
        errored = 0
        dry = opts["dry_run"]

        for user in User.objects.filter(is_active=True).select_related("profile"):
            if not is_dues_obligated(user):
                skipped_not_obligated += 1
                continue
            if user_paid_for_period(user, period):
                skipped_paid += 1
                continue
            if DuesReminder.objects.filter(
                user=user, dues_period=period, sent_at__gte=week_ago,
            ).exists():
                skipped_recent += 1
                continue

            if dry:
                self.stdout.write(f"  would send: {user.email}")
                sent += 1
                continue
            try:
                send_dues_reminder(user, period)
                DuesReminder.objects.create(user=user, dues_period=period)
                sent += 1
            except Exception as exc:
                errored += 1
                self.stderr.write(f"  failed for {user.email}: {exc}")

        verb = "Would send" if dry else "Sent"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {sent} reminder(s) for {period.name}. "
            f"Skipped: {skipped_paid} paid, {skipped_recent} reminded recently, "
            f"{skipped_not_obligated} not obligated. "
            f"Errors: {errored}."
        ))
