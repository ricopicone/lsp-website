"""Load the Applications Coordinator's yearly availability sheet from a CSV.

The sheet circulates as a PDF (e.g. "#2026-2027 LSP Analysts Availability");
save it as a CSV with a header row and import that — a CSV is reviewable,
diffable, and dry-runnable, where scraping the PDF layout is brittle.

Expected columns (header matched case-insensitively to AnalystFunction.name,
plus the special ``Analyst`` and ``Notes`` columns)::

    Analyst, Application Interviews, Advisor, Control analysis, Personal analysis, Notes

Cell values: ``Y``/``Yes`` → Yes, ``N``/``No`` → No, ``Uk``/``Unknown``/blank
→ Unknown (matching the sheet legend). Writes go through
``services.set_availability`` (source=import), so re-running is idempotent —
unchanged cells are left untouched.

    uv run python manage.py import_analyst_availability sheet.csv --dry-run
    uv run python manage.py import_analyst_availability sheet.csv --start 2026-05-20
"""

from __future__ import annotations

import csv
import datetime as _dt

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from availability import services
from availability.models import AnalystFunction, AvailabilitySpan

Status = AvailabilitySpan.Status

#: Cell text → status. Anything else (incl. blank) is treated as Unknown.
_STATUS = {
    "y": Status.YES, "yes": Status.YES,
    "n": Status.NO, "no": Status.NO,
    "uk": Status.UNKNOWN, "unknown": Status.UNKNOWN, "": Status.UNKNOWN,
}

#: Keyword → function slug, to attach a free-text Notes cell to the function it
#: names. Notes that match no function (or several) are reported, not guessed.
_NOTE_KEYWORDS = {
    "interview": "application-interviews",
    "advisor": "advisor",
    "advising": "advisor",
    "control": "control-analysis",
    "personal": "personal-analysis",
}

_SPECIAL_COLUMNS = {"analyst", "notes"}


def _normalize(name: str) -> str:
    return " ".join(name.strip().casefold().split())


class Command(BaseCommand):
    help = "Import analyst availability from a CSV of the yearly sheet."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the availability CSV.")
        parser.add_argument(
            "--start", default=None,
            help="Date the statuses take effect (YYYY-MM-DD). Defaults to today; "
            "for a back-dated sheet pass its 'as of' date.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change without writing anything.",
        )

    def handle(self, *args, **opts):
        path = opts["path"]
        dry_run = opts["dry_run"]
        start = self._parse_start(opts["start"])

        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                raise CommandError("CSV has no header row.")
            columns = self._resolve_columns(reader.fieldnames)
            rows = list(reader)

        profiles = self._index_profiles()

        changes = 0
        unmatched: list[str] = []
        unassigned_notes: list[str] = []

        for row in rows:
            raw_name = (row.get(self._analyst_key) or "").strip()
            if not raw_name:
                continue
            profile = profiles.get(_normalize(raw_name))
            if profile is None:
                unmatched.append(raw_name)
                continue

            note_target = self._note_target(row, columns, unassigned_notes, raw_name)

            for col, fn in columns.items():
                status = _STATUS.get((row.get(col) or "").strip().casefold())
                if status is None:
                    self.stderr.write(
                        f"  ! {raw_name}: unrecognized value "
                        f"{row.get(col)!r} for {fn.name} — treated as Unknown"
                    )
                    status = Status.UNKNOWN
                note = note_target.get(fn.pk, "")
                current = services.current_status(profile, fn)
                if current == status and not note:
                    continue
                changes += 1
                verb = "would set" if dry_run else "set"
                self.stdout.write(
                    f"  {verb} {raw_name} · {fn.name} → {Status(status).label}"
                    + (f"  ({note})" if note else "")
                )
                if not dry_run:
                    services.set_availability(
                        profile, fn, status,
                        on_date=start,
                        source=AvailabilitySpan.Source.IMPORT,
                        note=note,
                    )

        self._report(rows, changes, unmatched, unassigned_notes, dry_run)

    # -- helpers ----------------------------------------------------------

    def _parse_start(self, value):
        if not value:
            return timezone.localdate()
        try:
            return _dt.date.fromisoformat(value)
        except ValueError as exc:
            raise CommandError(f"--start must be YYYY-MM-DD: {exc}") from exc

    def _resolve_columns(self, fieldnames):
        """Map each function column header to its AnalystFunction.

        Records the actual 'Analyst' header (``self._analyst_key``) and rejects
        unknown columns so a typo'd header can't silently drop data.
        """
        by_name = {f.name.casefold(): f for f in AnalystFunction.objects.all()}
        columns: dict[str, AnalystFunction] = {}
        self._analyst_key = None
        for header in fieldnames:
            key = (header or "").strip()
            low = key.casefold()
            if low == "analyst":
                self._analyst_key = header
            elif low in _SPECIAL_COLUMNS:
                continue
            elif low in by_name:
                columns[header] = by_name[low]
            else:
                raise CommandError(
                    f"Unknown column {header!r}. Expected 'Analyst', 'Notes', "
                    f"or a function: {sorted(by_name)}."
                )
        if self._analyst_key is None:
            raise CommandError("CSV needs an 'Analyst' column.")
        if not columns:
            raise CommandError("CSV has no function columns to import.")
        return columns

    def _index_profiles(self):
        """{normalized full name: Profile} for eligible analysts."""
        index = {}
        for profile in services.eligible_profiles().select_related("user"):
            index[_normalize(profile.display_full_name)] = profile
            full = f"{profile.user.first_name} {profile.user.last_name}"
            index.setdefault(_normalize(full), profile)
        return index

    def _note_target(self, row, columns, unassigned, raw_name):
        """Map a row's Notes cell to a function span by keyword.

        Returns ``{function_id: note}``. A note that names no function — or
        more than one — is reported for the coordinator to place by hand
        (do-not-over-automate; we don't guess where an ambiguous note belongs).
        """
        note = (row.get("Notes") or row.get("notes") or "").strip()
        if not note:
            return {}
        low = note.casefold()
        slugs = {slug for kw, slug in _NOTE_KEYWORDS.items() if kw in low}
        if len(slugs) == 1:
            slug = next(iter(slugs))
            for fn in columns.values():
                if fn.slug == slug:
                    return {fn.pk: note}
        unassigned.append(f"{raw_name}: {note}")
        return {}

    def _report(self, rows, changes, unmatched, unassigned, dry_run):
        head = "Dry run — no changes written." if dry_run else "Import complete."
        self.stdout.write(self.style.SUCCESS(
            f"\n{head} {len(rows)} rows, {changes} cell change(s)."
        ))
        if unmatched:
            self.stdout.write(self.style.WARNING(
                f"\n{len(unmatched)} analyst(s) not matched to a Profile "
                f"(skipped — add the member or fix the name):"
            ))
            for name in unmatched:
                self.stdout.write(f"  - {name}")
        if unassigned:
            self.stdout.write(self.style.WARNING(
                f"\n{len(unassigned)} note(s) not tied to a single function "
                f"(place by hand in the console):"
            ))
            for line in unassigned:
                self.stdout.write(f"  - {line}")
