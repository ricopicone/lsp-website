"""Bulk-create Session rows for an event from a recurrence pattern (PROG-5).

Three pattern flavors:

    # every Thursday
    manage.py generate_sessions <slug> --weekly --weekdays TH \\
      --start 2026-09-01 --end 2026-12-15 --time 10:00-12:00

    # first and third Saturdays of each month
    manage.py generate_sessions <slug> --monthly --weekdays SA --weeks 1,3 \\
      --start 2026-09-01 --end 2026-12-31 --time 10:00-12:00

    # explicit dates
    manage.py generate_sessions <slug> --dates 2026-09-15,2026-10-13 \\
      --time 18:00-19:30 --location "Online"

Use ``--dry-run`` to preview without creating rows; ``--clear`` to delete
existing sessions for the event before creating new ones.
"""

from __future__ import annotations

from datetime import date, datetime, time

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from events.models import Event, Session
from events.scheduling import (
    generate_explicit,
    generate_monthly_ordinal,
    generate_weekly,
)


def _parse_time_range(value: str) -> tuple[time, time]:
    try:
        a, b = value.split("-", 1)
        return (
            datetime.strptime(a.strip(), "%H:%M").time(),
            datetime.strptime(b.strip(), "%H:%M").time(),
        )
    except (ValueError, AttributeError) as exc:
        raise CommandError(f"--time must look like HH:MM-HH:MM (got {value!r}): {exc}")


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CommandError(f"Could not parse date {value!r}: {exc}")


class Command(BaseCommand):
    help = "Bulk-create Session rows for an event from a recurrence pattern (PROG-5)."

    def add_arguments(self, parser):
        parser.add_argument("event_slug")
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--weekly", action="store_true")
        mode.add_argument("--monthly", action="store_true")
        mode.add_argument("--dates", help="Comma-separated YYYY-MM-DD dates.")

        parser.add_argument("--weekdays", help="Comma-separated: MO,TU,WE,TH,FR,SA,SU.")
        parser.add_argument("--weeks", help="Monthly only: comma-separated 1..5 or -1.")
        parser.add_argument("--start", help="Start date YYYY-MM-DD (weekly/monthly).")
        parser.add_argument("--end", help="End date YYYY-MM-DD (weekly/monthly).")
        parser.add_argument("--time", required=True, help="HH:MM-HH:MM (24h, project tz).")
        parser.add_argument("--location", default="", help="Per-session location.")
        parser.add_argument("--title", default="", help="Per-session title template.")
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete existing sessions before creating new ones.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be created without saving.",
        )

    def handle(self, *args, **opts):
        try:
            event = Event.objects.get(slug=opts["event_slug"])
        except Event.DoesNotExist as exc:
            raise CommandError(f"No event with slug {opts['event_slug']!r}.") from exc

        start_time, end_time = _parse_time_range(opts["time"])

        if opts["weekly"]:
            self._require(opts, "weekdays", "start", "end")
            windows = generate_weekly(
                start_date=_parse_date(opts["start"]),
                end_date=_parse_date(opts["end"]),
                weekdays=[w.strip() for w in opts["weekdays"].split(",") if w.strip()],
                start_time=start_time,
                end_time=end_time,
            )
        elif opts["monthly"]:
            self._require(opts, "weekdays", "weeks", "start", "end")
            windows = generate_monthly_ordinal(
                start_date=_parse_date(opts["start"]),
                end_date=_parse_date(opts["end"]),
                weekdays=[w.strip() for w in opts["weekdays"].split(",") if w.strip()],
                week_positions=[int(p) for p in opts["weeks"].split(",") if p.strip()],
                start_time=start_time,
                end_time=end_time,
            )
        else:
            dates = [_parse_date(d) for d in opts["dates"].split(",") if d.strip()]
            windows = generate_explicit(
                dates=dates, start_time=start_time, end_time=end_time
            )

        if not windows:
            raise CommandError("Pattern produced zero sessions.")

        next_seq = (
            event.sessions.order_by("-sequence").values_list("sequence", flat=True).first()
            or 0
        )
        title = opts["title"]
        location = opts["location"]

        self.stdout.write(f"Event: {event.title}")
        verb = "show" if opts["dry_run"] else "create"
        self.stdout.write(f"Will {verb} {len(windows)} session(s):")
        for i, w in enumerate(windows, start=1):
            self.stdout.write(
                f"  {i:>3}. {w.start_at.isoformat()} → {w.end_at.isoformat()}"
                + (f"  {location}" if location else "")
            )

        if opts["dry_run"]:
            return

        with transaction.atomic():
            if opts["clear"]:
                deleted, _ = event.sessions.all().delete()
                self.stdout.write(f"Cleared {deleted} existing session(s).")
                next_seq = 0

            created = 0
            for i, w in enumerate(windows):
                Session.objects.create(
                    event=event,
                    title=title,
                    start_at=w.start_at,
                    end_at=w.end_at,
                    location=location,
                    sequence=next_seq + i + 1,
                )
                created += 1

        self.stdout.write(self.style.SUCCESS(f"Created {created} session(s)."))

    def _require(self, opts, *names):
        missing = [n for n in names if not opts.get(n)]
        if missing:
            flags = ", ".join("--" + n for n in missing)
            raise CommandError(f"Missing required option(s) for this pattern: {flags}")
