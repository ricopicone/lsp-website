"""Repair offering workgroup names that drifted from their event's title.

``Event.ensure_workgroup`` snapshots the title into ``Workgroup.name`` at
creation; until task #568 nothing re-derived it, so any title edited afterwards
left the Workspace masthead and the three Parlêtre channels showing the old
wording while the program listing showed the new. The sync now runs on every
title save, which leaves only the rows that drifted beforehand — this is the
one-time sweep for those.

Idempotent, so it is safe to re-run. It calls
``Workgroup.sync_name_from_primary_event`` rather than re-deriving the name
itself: a second copy of that rule is what let the original drift go unnoticed.
The channel names follow through the ``renamed`` signal.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from workgroups.models import Workgroup


class Command(BaseCommand):
    help = "Re-sync offering workgroup names (and their channels) with event titles."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change without writing anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        renamed = 0
        for wg in Workgroup.objects.filter(
            kind__in=Workgroup.OFFERING_KINDS
        ).order_by("slug"):
            event = wg.primary_event()
            if event is None:
                continue
            wanted = event.title[:120]
            if wg.name == wanted:
                continue
            self.stdout.write(f"{wg.slug}\n  {wg.name!r}\n  → {wanted!r}")
            renamed += 1
            if not dry_run:
                wg.sync_name_from_primary_event()

        verb = "would be renamed" if dry_run else "renamed"
        self.stdout.write(self.style.SUCCESS(f"{renamed} {verb}."))
