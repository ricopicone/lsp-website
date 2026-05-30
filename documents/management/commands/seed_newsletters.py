"""Seed the 10 LSP Members Newsletter issues from the Wix export.

The newsletter was originally called "New Members Newsletter" (Vols 1–2)
and later renamed "Members Newsletter" (Vol 3). For catalog consistency
we title every issue "Members Newsletter X.Y".

Shanna Carlson de la Torre served as editor across the run and is set
as the sole listed author on every issue (members are encouraged to
edit and add additional contributors via the admin).

Idempotent — re-running updates by slug.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from documents.models import Document, DocumentAuthor

User = get_user_model()

EDITOR_FIRST = "Shanna"
EDITOR_LAST = "Carlson de la Torre"


@dataclass(frozen=True)
class SeedNewsletter:
    vol: int
    num: int
    filename: str
    pub_date: date


SEED: list[SeedNewsletter] = [
    SeedNewsletter(1, 1, "Newsletter 1.1.pdf", date(2022, 3,  1)),
    SeedNewsletter(1, 2, "Newsletter 1.2.pdf", date(2022, 5,  2)),
    SeedNewsletter(1, 3, "Newsletter 1.3.pdf", date(2022, 7,  5)),
    SeedNewsletter(1, 4, "Newsletter 1.4.pdf", date(2022, 9, 29)),
    SeedNewsletter(2, 1, "Newsletter 2.1.pdf", date(2023, 6,  1)),
    SeedNewsletter(2, 2, "Newsletter 2.2.pdf", date(2023, 8,  1)),
    SeedNewsletter(2, 3, "Newsletter 2.3.pdf", date(2023, 10, 1)),
    SeedNewsletter(2, 4, "Newsletter 2.4.pdf", date(2023, 12, 1)),
    SeedNewsletter(3, 1, "Newsletter 3.1.pdf", date(2024, 2,  1)),
    SeedNewsletter(3, 2, "Newsletter 3.2.pdf", date(2024, 4, 29)),
]


class Command(BaseCommand):
    help = "Seed the 10 LSP Members Newsletter issues. Idempotent — updates by slug."

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

        editor = User.objects.filter(
            first_name__iexact=EDITOR_FIRST,
            last_name__iexact=EDITOR_LAST,
        ).first()
        if editor is None:
            self.stderr.write(self.style.WARNING(
                f"Editor not found ({EDITOR_FIRST} {EDITOR_LAST}) — "
                f"newsletters will be created without an author link."
            ))

        created = updated = 0
        missing: list[str] = []

        for entry in SEED:
            pdf_path = src / entry.filename
            if not pdf_path.is_file():
                missing.append(entry.filename)
                self.stderr.write(self.style.WARNING(f"  missing: {entry.filename}"))
                continue

            slug = f"newsletter-{entry.vol}-{entry.num}"
            title = f"Members Newsletter {entry.vol}.{entry.num}"
            summary = (
                f"Volume {entry.vol}, Issue {entry.num} — "
                f"{entry.pub_date.strftime('%B %Y')}."
            )
            description = (
                "Edited by Shanna Carlson de la Torre. The newsletter was "
                "originally called *New Members Newsletter* and was renamed "
                "*Members Newsletter* during Volume 3 as its scope evolved."
            )

            existing = Document.objects.filter(slug=slug).first()
            action = "update" if existing else "create"
            if dry_run:
                self.stdout.write(f"  {action}: {slug}  ←  {entry.filename}")
                if existing:
                    updated += 1
                else:
                    created += 1
                continue

            with transaction.atomic():
                d = existing or Document(slug=slug)
                d.title = title
                d.category = Document.Category.NEWSLETTER
                d.summary = summary
                d.description = description
                d.effective_date = entry.pub_date
                d.display_order = entry.vol * 10 + entry.num
                d.listing_visibility = Document.Visibility.PUBLIC
                # Members-only PDF — these contain member-specific content
                # (interviews, new-member profiles). The listing entry stays
                # public so the historical run is visible.
                d.pdf_visibility = Document.Visibility.MEMBERS
                with pdf_path.open("rb") as fh:
                    d.file.save(pdf_path.name, File(fh), save=False)
                d.save()

                # Author: replace authorships with just the editor (idempotent).
                if editor is not None:
                    DocumentAuthor.objects.filter(document=d).delete()
                    DocumentAuthor.objects.create(
                        document=d, user=editor, display_order=0,
                    )

                if existing:
                    updated += 1
                    self.stdout.write(f"  updated: {slug}")
                else:
                    created += 1
                    self.stdout.write(self.style.SUCCESS(f"  created: {slug}"))

        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write("")
        self.stdout.write(
            f"{prefix}{created} created, {updated} updated, "
            f"{len(missing)} missing file(s)."
        )
        if missing:
            self.stdout.write(self.style.WARNING("Missing source files:"))
            for name in missing:
                self.stdout.write(f"  - {name}")
