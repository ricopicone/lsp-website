"""Send dues reminders to obligated unpaid members (REG-12).

Wire via a daily systemd timer on the EC2 host. Each DuesPeriod carries
its own ``reminder_interval_days`` (default 7) — the treasurer can change
it via the treasurer admin Settings tab. A user is skipped if they were
already reminded within that interval.

Skips:
- users not in ``DUES_OBLIGATED_ROLES``
- users whose unified-ledger dues state for the current period is paid,
  waived, or unminted (``None`` — no charge, nothing to chase)
- users whose last reminder was within the period's reminder_interval_days
- when no current period exists, or it's not yet past due date
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from notifications.categories import Category
from payments import ledger
from payments import notifications as notify_payments
from payments.dues import is_dues_obligated
from payments.emails import send_dues_reminder
from payments.models import DuesPeriod, DuesReminder
from payments.sending import ThrottledSender

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

        interval_cutoff = timezone.now() - timedelta(days=period.reminder_interval_days)
        sent = 0
        skipped_paid = 0
        skipped_recent = 0
        skipped_not_obligated = 0
        errored = 0
        dry = opts["dry_run"]
        sender = ThrottledSender()

        for user in User.objects.filter(is_active=True).select_related("profile"):
            if not is_dues_obligated(user):
                skipped_not_obligated += 1
                continue
            state = ledger.member_account(user)["dues_state"]
            if state in (None, "paid", "waived"):
                skipped_paid += 1
                continue
            if DuesReminder.objects.filter(
                user=user, dues_period=period, sent_at__gte=interval_cutoff,
            ).exists():
                skipped_recent += 1
                continue

            if dry:
                self.stdout.write(f"  would send: {user.email}")
                sent += 1
                continue
            try:
                notify_payments.dues_reminder_inapp(user, period)  # bell row
                if notify_payments.should_email(user, Category.DUES_REMINDER):
                    sender.send(send_dues_reminder, user, period)
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
