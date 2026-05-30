"""Send weekly tuition reminders to in-training students (M7.5).

Mirrors send_dues_reminders. Sends to active users whose Profile.role is
in IN_TRAINING_ROLES and either:

- have no TuitionEnrollment for the current period, OR
- have status=COMMITTED but no PAID_IN_FULL transition yet, OR
- have status=PAYMENT_PLAN with an overdue unpaid installment

Throttled to one email per user per week via TuitionReminder rows.
Only runs once the period's decision_due_date has passed (~September 1
in standard configuration).
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Profile
from payments.emails import send_tuition_reminder
from payments.models import TuitionEnrollment, TuitionPeriod, TuitionReminder

User = get_user_model()


def _needs_reminder(enrollment: TuitionEnrollment | None, today) -> bool:
    """Decide whether this user should receive a reminder right now."""
    if enrollment is None:
        return True  # no decision yet
    if enrollment.status == TuitionEnrollment.Status.PAID_IN_FULL:
        return False
    if enrollment.status == TuitionEnrollment.Status.SKIPPING:
        return False  # explicit no — don't pester
    if enrollment.status == TuitionEnrollment.Status.COMMITTED:
        return True  # committed but unpaid
    if enrollment.status == TuitionEnrollment.Status.PAYMENT_PLAN:
        # Overdue installment?
        return enrollment.installments.filter(
            paid=False, due_date__lte=today,
        ).exists()
    return False


class Command(BaseCommand):
    help = "Send weekly tuition reminders to in-training students."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be sent without sending or logging.",
        )

    def handle(self, *args, **opts):
        period = TuitionPeriod.current()
        if period is None:
            self.stdout.write("No current TuitionPeriod; nothing to do.")
            return

        today = timezone.now().date()
        if today < period.decision_due_date:
            self.stdout.write(
                f"Period {period.name} decision-due is "
                f"{period.decision_due_date}; not yet — skipping reminders."
            )
            return

        interval_cutoff = timezone.now() - timedelta(days=period.reminder_interval_days)
        sent = 0
        skipped_done = 0
        skipped_recent = 0
        skipped_not_owing = 0
        errored = 0
        dry = opts["dry_run"]

        eligible_users = User.objects.filter(
            is_active=True, profile__role__in=Profile.IN_TRAINING_ROLES,
        ).select_related("profile")

        for user in eligible_users:
            if not user.profile.owes_tuition:
                skipped_not_owing += 1
                continue

            enrollment = TuitionEnrollment.objects.filter(
                user=user, tuition_period=period,
            ).first()
            if not _needs_reminder(enrollment, today):
                skipped_done += 1
                continue

            if TuitionReminder.objects.filter(
                user=user, tuition_period=period, sent_at__gte=interval_cutoff,
            ).exists():
                skipped_recent += 1
                continue

            if dry:
                self.stdout.write(f"  would send: {user.email}")
                sent += 1
                continue
            try:
                send_tuition_reminder(user, period, enrollment=enrollment)
                TuitionReminder.objects.create(user=user, tuition_period=period)
                sent += 1
            except Exception as exc:
                errored += 1
                self.stderr.write(f"  failed for {user.email}: {exc}")

        verb = "Would send" if dry else "Sent"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {sent} reminder(s) for {period.name}. "
            f"Skipped: {skipped_done} resolved, {skipped_recent} reminded recently, "
            f"{skipped_not_owing} not owing. Errors: {errored}."
        ))
