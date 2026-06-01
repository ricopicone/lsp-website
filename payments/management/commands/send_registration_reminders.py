"""Reminders for the faculty-approval registration flow.

Two kinds, both throttled via ``Registration.reminded_at`` (reset on each
state transition):

- **Faculty approval reminders** — one digest per event whose faculty have
  registrations still ``PENDING_APPROVAL``.
- **Student payment reminders** — to registrants whose registration was
  *approved* (``decided_at`` set) and is ``AWAITING_PAYMENT`` but unpaid.

Wire via the same daily systemd timer as the dues/tuition reminders on the
EC2 host. Default interval is 3 days; pass ``--interval-days`` to change it.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from payments.emails import send_approval_reminder, send_payment_reminder
from payments.sending import ThrottledSender
from registrations.models import Registration


class Command(BaseCommand):
    help = "Send faculty-approval and student-payment reminders."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report without sending or stamping.")
        parser.add_argument("--interval-days", type=int, default=3,
                            help="Min days between reminders for the same item.")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        cutoff = timezone.now() - timedelta(days=opts["interval_days"])
        due = Q(reminded_at__isnull=True) | Q(reminded_at__lt=cutoff)
        sender = ThrottledSender()

        # --- Faculty approval reminders (one digest per event) ---
        pending_due = (
            Registration.objects.filter(status=Registration.Status.PENDING_APPROVAL)
            .filter(due).select_related("event")
        )
        events = {}
        for reg in pending_due:
            events[reg.event_id] = reg.event
        faculty_sent = 0
        for event in events.values():
            pending = event.registrations.filter(
                status=Registration.Status.PENDING_APPROVAL
            )
            count = pending.count()
            if not count:
                continue
            if dry:
                self.stdout.write(f"  would remind faculty of '{event.title}' ({count} pending)")
            else:
                sender.send(send_approval_reminder, event, count)
                pending.update(reminded_at=timezone.now())
            faculty_sent += 1

        # --- Student payment reminders (approved but unpaid) ---
        awaiting = (
            Registration.objects.filter(
                status=Registration.Status.AWAITING_PAYMENT,
                decided_at__isnull=False,       # came through approval
                quoted_amount__gt=0,
            ).filter(due).select_related("event", "user")
        )
        student_sent = 0
        for reg in awaiting:
            if dry:
                self.stdout.write(f"  would remind {reg.user.email} to pay for '{reg.event.title}'")
            else:
                sender.send(send_payment_reminder, reg)
                reg.reminded_at = timezone.now()
                reg.save(update_fields=["reminded_at"])
            student_sent += 1

        verb = "Would send" if dry else "Sent"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {faculty_sent} faculty approval reminder(s) and "
            f"{student_sent} student payment reminder(s)."
        ))
