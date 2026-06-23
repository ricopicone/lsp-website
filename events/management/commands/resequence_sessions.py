"""Renumber session ``sequence`` values to match chronological (``start_at``)
order. The signals in ``events/signals.py`` keep this in sync going forward;
this command backfills existing events whose numbers drifted (e.g. a session
added out of date order before the signals existed).

    manage.py resequence_sessions --slug topology-direction-of-treatment-2026-27
    manage.py resequence_sessions --all
    manage.py resequence_sessions --all --dry-run
"""

from django.core.management.base import BaseCommand, CommandError

from events.models import Event


class Command(BaseCommand):
    help = "Renumber Session.sequence to match chronological (start_at) order."

    def add_arguments(self, parser):
        parser.add_argument("--slug", help="Resequence a single event by slug.")
        parser.add_argument(
            "--all", action="store_true", help="Resequence every event."
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing.",
        )

    def handle(self, *args, **opts):
        if bool(opts["slug"]) == bool(opts["all"]):
            raise CommandError("Pass exactly one of --slug <slug> or --all.")

        if opts["slug"]:
            try:
                events = [Event.objects.get(slug=opts["slug"])]
            except Event.DoesNotExist:
                raise CommandError(f"No event with slug {opts['slug']!r}.")
        else:
            events = Event.objects.all().order_by("title")

        total_changed = 0
        for event in events:
            sessions = list(event.sessions.order_by("start_at", "id"))
            changes = [
                (s, i)
                for i, s in enumerate(sessions, start=1)
                if s.sequence != i
            ]
            if not changes:
                continue
            total_changed += len(changes)
            self.stdout.write(f"{event.title}:")
            for s, new in changes:
                self.stdout.write(
                    f"  {s.start_at.date().isoformat()}  #{s.sequence} → #{new}"
                )
            if not opts["dry_run"]:
                event.resequence_sessions()

        verb = "Would renumber" if opts["dry_run"] else "Renumbered"
        self.stdout.write(
            self.style.SUCCESS(f"{verb} {total_changed} session(s).")
        )
