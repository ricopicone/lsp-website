"""Seed the initial Works catalog from the Wix export.

Only Palimpsests are present in ``../wix-files/`` — Passages were under
The Archive on Wix (the unused discussion-board tab) and don't exist as
PDFs. Author names are matched against existing Users by first/last
name; unmatched authors are stored in ``external_authors`` so the work
is still seeded with attribution.

Idempotent — re-running updates by slug.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from works.models import Work, WorkAuthor

User = get_user_model()


@dataclass(frozen=True)
class SeedWork:
    slug: str
    title: str
    kind: str
    filename: str
    author_names: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    publication_date: date | None = None
    abstract: str = ""
    listing_visibility: str = Work.Visibility.PUBLIC
    pdf_visibility: str = Work.PDFVisibility.MEMBERS


SEED: list[SeedWork] = [
    SeedWork(
        slug="palimpsest-a-voice",
        title="Palimpsest: A Voice",
        kind=Work.Kind.PALIMPSEST,
        filename="Palimpsest_a Voice.pdf",
        author_names=(("Laura", "Rivera Rodriguez"),),
        publication_date=date(2026, 5, 1),
        abstract="Read in Berkeley, CA on May 1, 2026.",
    ),
    SeedWork(
        slug="palimpsest-hablando-hasta-por-los-codos",
        title="Palimpsest: Hablando hasta por los codos",
        kind=Work.Kind.PALIMPSEST,
        filename="Palimpsest_Hablando hasta por los codos.pdf",
        author_names=(("Laura", "Rivera Rodriguez"),),
        publication_date=date(2026, 5, 1),
        abstract="Read in Berkeley, CA on May 1, 2026.",
    ),
]


def _resolve_user(first: str, last: str):
    """Case-insensitive first+last lookup; returns User or None."""
    return User.objects.filter(
        first_name__iexact=first, last_name__iexact=last,
    ).first()


class Command(BaseCommand):
    help = "Seed initial Works from ../wix-files/. Idempotent — updates by slug."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-dir",
            default=str(Path(settings.BASE_DIR).parent / "wix-files"),
            help="Directory containing the source PDFs (default: ../wix-files/).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be created/updated without writing anything.",
        )

    def handle(self, *args, source_dir: str, dry_run: bool, **opts):
        src = Path(source_dir)
        if not src.is_dir():
            raise CommandError(f"Source directory not found: {src}")

        created = updated = 0
        missing_files: list[str] = []
        unmatched_authors: list[tuple[str, str, str]] = []

        for entry in SEED:
            pdf_path = src / entry.filename
            if not pdf_path.is_file():
                missing_files.append(entry.filename)
                self.stderr.write(self.style.WARNING(f"  missing: {entry.filename}"))
                continue

            # Resolve authors
            users: list = []
            externals: list[str] = []
            for first, last in entry.author_names:
                u = _resolve_user(first, last)
                if u is None:
                    externals.append(f"{first} {last}")
                    unmatched_authors.append((entry.slug, first, last))
                else:
                    users.append(u)

            existing = Work.objects.filter(slug=entry.slug).first()
            action = "update" if existing else "create"

            if dry_run:
                authors_note = (
                    ", ".join(f"{u.first_name} {u.last_name}" for u in users)
                    or "(no matched LSP authors)"
                )
                self.stdout.write(
                    f"  {action}: {entry.slug}  ←  {entry.filename}  "
                    f"[authors: {authors_note}]"
                )
                if existing:
                    updated += 1
                else:
                    created += 1
                continue

            with transaction.atomic():
                w = existing or Work(slug=entry.slug)
                w.title = entry.title
                w.kind = entry.kind
                w.abstract = entry.abstract
                w.publication_date = entry.publication_date
                w.listing_visibility = entry.listing_visibility
                w.pdf_visibility = entry.pdf_visibility
                w.external_authors = "; ".join(externals)
                with pdf_path.open("rb") as fh:
                    w.pdf.save(pdf_path.name, File(fh), save=False)
                w.save()
                # Replace authorships with the resolved list, in order.
                WorkAuthor.objects.filter(work=w).delete()
                for i, user in enumerate(users):
                    WorkAuthor.objects.create(work=w, user=user, display_order=i)

                if existing:
                    updated += 1
                    self.stdout.write(f"  updated: {entry.slug}")
                else:
                    created += 1
                    self.stdout.write(self.style.SUCCESS(f"  created: {entry.slug}"))

        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write("")
        self.stdout.write(
            f"{prefix}{created} created, {updated} updated, "
            f"{len(missing_files)} missing file(s)."
        )
        if missing_files:
            self.stdout.write(self.style.WARNING("Missing source files:"))
            for name in missing_files:
                self.stdout.write(f"  - {name}")
        if unmatched_authors:
            self.stdout.write(self.style.WARNING(
                "Unmatched authors (stored as external_authors):"
            ))
            for slug, first, last in unmatched_authors:
                self.stdout.write(f"  - {slug}: {first} {last}")
