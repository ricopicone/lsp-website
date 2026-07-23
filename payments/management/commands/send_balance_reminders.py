"""Send weekly reminders to members with an outstanding unified-ledger
balance (task #450 phase D).

Unlike ``send_dues_reminders``/``send_tuition_reminders`` (each scoped to
one category's period), this reminds on the member's *whole* account
balance — dues, tuition, and event fees, whatever's unpaid — computed by
``payments.ledger.accounts_overview``, the same helper the treasurer's
Accounts view uses for its "Owing" figure. The number in the email is
therefore guaranteed to match what the treasurer sees.

Gate: mirrors ``send_dues_reminders`` — only runs once the current
``DuesPeriod`` is past its due date (a proxy for "the AY billing cycle has
started"; there's no independent "balance period").

Skips:
- personas and inactive users
- balance <= 0 (nothing owed)
- users whose last balance reminder was within 7 days
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from notifications.categories import Category
from payments import ledger
from payments import notifications as notify_payments
from payments.emails import send_balance_reminder
from payments.models import BalanceReminder, DuesPeriod
from payments.sending import ThrottledSender

REMINDER_INTERVAL_DAYS = 7


class Command(BaseCommand):
    help = "Send weekly outstanding-balance reminders to members who owe money."

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
        if today <= period.due_date:
            self.stdout.write(
                f"Period {period.name} not yet past due ({period.due_date}); "
                "skipping balance reminders."
            )
            return

        interval_cutoff = timezone.now() - timedelta(days=REMINDER_INTERVAL_DAYS)
        sent = 0
        skipped_no_balance = 0
        skipped_recent = 0
        errored = 0
        dry = opts["dry_run"]
        sender = ThrottledSender()

        for row in ledger.accounts_overview():
            user = row["user"]
            profile = getattr(user, "profile", None)
            if profile is None or profile.is_persona or not user.is_active:
                continue
            balance = row["owes"]
            if balance <= 0:
                skipped_no_balance += 1
                continue
            if BalanceReminder.objects.filter(
                user=user, sent_at__gte=interval_cutoff,
            ).exists():
                skipped_recent += 1
                continue

            if dry:
                self.stdout.write(f"  would send: {user.email} (${balance})")
                sent += 1
                continue
            try:
                notify_payments.balance_reminder_inapp(user, balance)  # bell row
                if notify_payments.should_email(user, Category.BALANCE_REMINDER):
                    sender.send(send_balance_reminder, user, balance)
                BalanceReminder.objects.create(user=user, balance=balance)
                sent += 1
            except Exception as exc:
                errored += 1
                self.stderr.write(f"  failed for {user.email}: {exc}")

        verb = "Would send" if dry else "Sent"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {sent} balance reminder(s). "
            f"Skipped: {skipped_no_balance} no balance owed, "
            f"{skipped_recent} reminded recently. Errors: {errored}."
        ))
