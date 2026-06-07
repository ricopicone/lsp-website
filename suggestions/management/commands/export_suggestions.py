"""Export member suggestions as Claude Code briefs.

    uv run python manage.py export_suggestions               # actionable, default dir
    uv run python manage.py export_suggestions --unexported   # only not-yet-exported
    uv run python manage.py export_suggestions --ids 3 7 9 --out /tmp/briefs
    uv run python manage.py export_suggestions --status done --with-screenshots

Writes one ``suggestion-<id>.md`` per row plus an ``INDEX.md`` checklist, and
stamps ``exported_at`` on each exported row.
"""

from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from suggestions.export import write_briefs
from suggestions.models import Suggestion

DEFAULT_OUT = "suggestions-briefs"


class Command(BaseCommand):
    help = "Export member suggestions as structured markdown briefs for Claude Code."

    def add_arguments(self, parser):
        parser.add_argument(
            "--status", action="append", default=[],
            help="Filter by status (repeatable). Default: the actionable statuses "
                 "(new, acknowledged, planned, in_progress).",
        )
        parser.add_argument(
            "--ids", nargs="+", type=int, default=None,
            help="Export only these suggestion ids (ignores --status).",
        )
        parser.add_argument(
            "--unexported", action="store_true",
            help="Only suggestions not yet exported (exported_at is empty).",
        )
        parser.add_argument(
            "--since", default=None,
            help="Only suggestions created on/after this date (YYYY-MM-DD).",
        )
        parser.add_argument("--out", default=DEFAULT_OUT, help="Output directory.")
        parser.add_argument(
            "--with-screenshots", action="store_true",
            help="Also download each suggestion's screenshot into <out>/screenshots/.",
        )

    def handle(self, *args, **opts):
        qs = Suggestion.objects.select_related("submitted_by")

        if opts["ids"]:
            qs = qs.filter(pk__in=opts["ids"])
        else:
            statuses = opts["status"] or list(Suggestion.ACTIONABLE_STATUSES)
            invalid = [s for s in statuses if s not in Suggestion.Status.values]
            if invalid:
                raise CommandError(f"Unknown status(es): {', '.join(invalid)}")
            qs = qs.filter(status__in=statuses)

        if opts["unexported"]:
            qs = qs.filter(exported_at__isnull=True)

        if opts["since"]:
            try:
                day = dt.datetime.strptime(opts["since"], "%Y-%m-%d").date()
            except ValueError as exc:
                raise CommandError("--since must be YYYY-MM-DD") from exc
            start = timezone.make_aware(dt.datetime.combine(day, dt.time.min))
            qs = qs.filter(created_at__gte=start)

        if not qs.exists():
            self.stdout.write("No suggestions matched — nothing exported.")
            return

        written = write_briefs(qs, opts["out"], with_screenshots=opts["with_screenshots"])
        self.stdout.write(self.style.SUCCESS(
            f"Exported {len(written)} suggestion(s) to ./{opts['out']}/ "
            f"(INDEX.md + {len(written)} brief(s)). Point a Claude Code session there."
        ))
