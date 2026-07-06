"""The automatic yearly availability reminder.

When ``AvailabilitySettings.reminder_mode`` is Automatic, this emails every
Analyst of the School a review request once per academic year (the first time
it runs on/after the Sept-1 start). ``last_auto_reminder_ay`` guards against
re-sending. When set to Review first, it does nothing — the coordinator sends
by hand from the console.

Wire it as a daily host timer at launch (member-facing — keep off until then).
``--force`` ignores the mode/once-a-year guards; ``--dry-run`` reports only.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from availability import notifications, services
from availability.models import AvailabilitySettings
from events.models import current_academic_year


class Command(BaseCommand):
    help = "Send the automatic yearly availability review reminder, if enabled."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--force", action="store_true",
            help="Send regardless of the mode and once-a-year guard.",
        )

    def handle(self, *args, **opts):
        cfg = AvailabilitySettings.load()
        ay = current_academic_year()

        if not opts["force"]:
            if cfg.reminder_mode != AvailabilitySettings.Mode.AUTO:
                self.stdout.write("Reminders are set to review-first; nothing sent.")
                return
            if cfg.last_auto_reminder_ay == ay:
                self.stdout.write(f"Already sent for {ay}; nothing to do.")
                return

        profiles = (
            services.eligible_profiles()
            .filter(is_persona=False, user__is_active=True)
            .select_related("user")
        )
        sent = 0
        for profile in profiles:
            if not opts["dry_run"]:
                notifications.request_review(profile.user)
            sent += 1

        if not opts["dry_run"]:
            cfg.last_auto_reminder_ay = ay
            cfg.save(update_fields=["last_auto_reminder_ay"])

        verb = "Would send" if opts["dry_run"] else "Sent"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} availability reminders to {sent} analyst(s) for {ay}."
        ))
