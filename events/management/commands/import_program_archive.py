"""Import past program PDFs into ``events.ArchivedProgram``.

Scans a directory for program PDFs whose filenames carry an academic year —
e.g. ``2008-2009.pdf``, ``2010 - 2011 LSP Program.pdf``, ``PROGRAM
2008-2009.pdf``, ``1994.pdf`` — normalizes the year, dedupes (shortest filename
wins per year), and stores each in private storage. Idempotent: an existing
year is skipped unless ``--update`` is given.

    manage.py import_program_archive /path/to/wix-files
    manage.py import_program_archive /path/to/wix-files --dry-run

Non-program PDFs in the same folder (bylaws, founding texts, newsletters with
dotted dates like ``2022.12.14 …``) are ignored — only filenames that *begin*
with an academic-year token are taken.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from events.models import ArchivedProgram

_RANGE = re.compile(r"^(?:PROGRAM\s+)?(\d{4})\s*[-–]\s*(\d{4})", re.IGNORECASE)
_SINGLE = re.compile(r"^(\d{4})(?:\s|$)")
_DOTTED_DATE = re.compile(r"^\d{4}\.\d")  # e.g. "2022.12.14 LSP ByLaws"


def _academic_year(stem: str) -> str | None:
    m = _RANGE.match(stem)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    if _DOTTED_DATE.match(stem):
        return None
    m = _SINGLE.match(stem)
    return m.group(1) if m else None


class Command(BaseCommand):
    help = "Import past program PDFs into events.ArchivedProgram."

    def add_arguments(self, parser):
        parser.add_argument("directory", help="Folder containing the program PDFs.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would be imported without writing.")
        parser.add_argument("--update", action="store_true",
                            help="Replace the file for years that already exist.")

    def handle(self, *args, **opts):
        root = Path(opts["directory"]).expanduser()
        if not root.is_dir():
            raise CommandError(f"Not a directory: {root}")

        # Collect (academic_year -> chosen path); shortest filename wins per year.
        chosen: dict[str, Path] = {}
        for path in sorted(root.glob("*.pdf")):
            ay = _academic_year(path.stem)
            if ay is None:
                continue
            cur = chosen.get(ay)
            if cur is None or len(path.name) < len(cur.name):
                chosen[ay] = path

        if not chosen:
            self.stdout.write("No program PDFs found.")
            return

        dry = opts["dry_run"]
        created = updated = skipped = 0
        for ay in sorted(chosen, reverse=True):
            path = chosen[ay]
            existing = ArchivedProgram.objects.filter(academic_year=ay).first()
            if existing and not opts["update"]:
                self.stdout.write(f"SKIP  {ay:12} (exists)  <- {path.name}")
                skipped += 1
                continue
            self.stdout.write(
                f"{'WOULD ' if dry else ''}{'UPDATE' if existing else 'CREATE'} "
                f"{ay:12} <- {path.name}"
            )
            if dry:
                continue
            obj = existing or ArchivedProgram(academic_year=ay)
            with open(path, "rb") as fh:
                obj.file.save(f"{ay}.pdf", File(fh), save=True)
            if existing:
                updated += 1
            else:
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. created={created} updated={updated} skipped={skipped}"
            + (" (dry-run)" if dry else "")
        ))
