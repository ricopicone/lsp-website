"""Send pre-meeting reminders ~15 minutes before each scheduled meeting.

Run frequently on the host (every ~5 min). A meeting is reminded once, when it
first enters the lead-time window: not cancelled, in a group with
``meeting_reminders`` on, and not already stamped ``reminder_sent_at``.

Member-facing email — like the dues/registration reminders, enable its host
timer only at launch.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from workgroups import notifications as notify_groups
from workgroups.models import WorkgroupMeeting


class Command(BaseCommand):
    help = ("Email members a reminder ~15 minutes before their meetings, and "
            "event registrants the day before each session.")

    def add_arguments(self, parser):
        parser.add_argument("--lead-minutes", type=int, default=15,
                            help="How far ahead of start to remind.")
        parser.add_argument("--session-lead-hours", type=int, default=24,
                            help="How far ahead of an event session to remind "
                                 "its registrants (task #716).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report without sending or stamping.")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        now = timezone.now()
        window_end = now + timedelta(minutes=opts["lead_minutes"])

        due = (
            WorkgroupMeeting.objects
            .filter(
                cancelled=False,
                reminder_sent_at__isnull=True,
                starts_at__gt=now,            # not already started
                starts_at__lte=window_end,    # within the lead-time window
                workgroup__meeting_reminders=True,
            )
            .select_related("workgroup")
        )

        meetings = 0
        people = 0
        for meeting in due:
            label = meeting.title or meeting.workgroup.name
            if dry:
                self.stdout.write(f"would remind: {label} @ {meeting.starts_at:%Y-%m-%d %H:%M}")
                meetings += 1
                continue
            people += notify_groups.meeting_reminder(meeting)
            meeting.reminder_sent_at = now
            meeting.save(update_fields=["reminder_sent_at"])
            meetings += 1

        verb = "would remind for" if dry else "reminded for"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {meetings} meeting(s)" + ("" if dry else f", {people} member-notice(s)")
        ))
        self._remind_sessions(now, opts["session_lead_hours"], dry)

    def _remind_sessions(self, now, lead_hours: int, dry: bool) -> None:
        """Event sessions (task #716): the day-before reminder to confirmed
        registrants. Rides this command because the host already runs it every
        five minutes; a session is reminded once, stamped on the row, and only
        while its event is published and still has someone to tell."""
        from events.models import Session
        from payments import notifications as notify_payments

        due = (
            Session.objects
            .filter(
                reminder_sent_at__isnull=True,
                start_at__gt=now,
                start_at__lte=now + timedelta(hours=lead_hours),
                event__published=True,
            )
            .select_related("event")
            .order_by("start_at")
        )
        sessions = people = 0
        for session in due:
            if dry:
                self.stdout.write(
                    f"would remind registrants: {session} @ {session.start_at:%Y-%m-%d %H:%M}"
                )
                sessions += 1
                continue
            people += notify_payments.session_reminder(session)
            session.reminder_sent_at = now
            session.save(update_fields=["reminder_sent_at"])
            sessions += 1
        verb = "would remind for" if dry else "reminded for"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {sessions} event session(s)"
            + ("" if dry else f", {people} registrant-notice(s)")
        ))
