"""Apply a curated citation mapping to existing Works (task #465).

The mapping JSON is hand-reviewed (kept under import-staging/), one entry
per work::

    [{"slug": "...", "fields": {"container_title": "...", ...}}, ...]

Only fields in ``Work.STRUCTURED_CITATION_FIELDS`` are allowed, and only
currently-empty fields are filled — member edits are never overwritten.
Idempotent; run with ``--dry-run`` first.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from works.models import Work


class Command(BaseCommand):
    help = "Backfill structured citation fields from a reviewed JSON mapping."

    def add_arguments(self, parser):
        parser.add_argument("mapping", help="Path to the reviewed JSON mapping file.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        with open(opts["mapping"]) as fh:
            entries = json.load(fh)
        allowed = set(Work.STRUCTURED_CITATION_FIELDS)
        applied = skipped = 0
        for entry in entries:
            slug, fields = entry.get("slug"), entry.get("fields") or {}
            bad = set(fields) - allowed
            if bad:
                raise CommandError(f"{slug}: fields not allowed: {sorted(bad)}")
            try:
                work = Work.objects.get(slug=slug)
            except Work.DoesNotExist:
                raise CommandError(f"No work with slug {slug!r}")
            changed = []
            for name, value in fields.items():
                if getattr(work, name):
                    skipped += 1
                    continue
                setattr(work, name, value)
                changed.append(name)
            if changed:
                applied += len(changed)
                verb = "would set" if opts["dry_run"] else "set"
                self.stdout.write(f"{slug}: {verb} {', '.join(changed)}")
                if not opts["dry_run"]:
                    work.save(update_fields=changed + ["updated_at"])
        self.stdout.write(self.style.SUCCESS(
            f"{applied} field(s) {'would be ' if opts['dry_run'] else ''}applied, "
            f"{skipped} skipped (already set)."
        ))
