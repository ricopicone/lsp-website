"""Seed the initial 10 Documents from the Wix export.

Reads PDFs from ``../wix-files/`` (a sibling of the lsp-website repo
where the Wix export was unpacked) and creates ``Document`` rows with
canonical titles, slugs, categories, and summaries.

Idempotent: re-running updates the existing rows by slug rather than
duplicating. Use ``--dry-run`` to preview what would change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from documents.models import Document


@dataclass(frozen=True)
class SeedDoc:
    slug: str
    title: str
    category: str
    filename: str
    summary: str
    effective_date: date | None = None
    display_order: int = 0


SEED: list[SeedDoc] = [
    # ---- Governance ----
    SeedDoc(
        slug="bylaws",
        title="Bylaws of the Lacanian School of Psychoanalysis",
        category=Document.Category.GOVERNANCE,
        filename="2024.12.29 LSP Bylaws.pdf",
        summary="The governing bylaws of the school.",
        effective_date=date(2024, 12, 29),
        display_order=10,
    ),
    SeedDoc(
        slug="ethical-complaints-process",
        title="Process for Handling Ethical Complaints",
        category=Document.Category.GOVERNANCE,
        filename="LSP Complaints & Ethics Final 2024.12.08.pdf",
        summary="How the school handles complaints and ethical concerns.",
        effective_date=date(2024, 12, 8),
        display_order=20,
    ),
    # ---- Formation Guidelines ----
    SeedDoc(
        slug="analyst-formation-guidelines",
        title="Analyst Formation Guidelines",
        category=Document.Category.FORMATION,
        filename="LSP Analyst Formation 2026-03-24.pdf",
        summary="Current guidelines for the analyst formation pathway.",
        effective_date=date(2026, 3, 24),
        display_order=10,
    ),
    SeedDoc(
        slug="scholar-formation-guidelines",
        title="Scholar Formation Guidelines",
        category=Document.Category.FORMATION,
        filename="LSP Scholar Formation 2023.01.09.pdf",
        summary="Current guidelines for the scholar formation pathway.",
        effective_date=date(2023, 1, 9),
        display_order=20,
    ),
    # ---- Founding Texts ----
    SeedDoc(
        slug="founding-paper-patsalides",
        title="LSP Founding Paper — Patsalides",
        category=Document.Category.FOUNDING,
        filename="LSP Founding Paper Patsalides.pdf",
        summary="One of the school's founding texts on analyst formation.",
        display_order=10,
    ),
    SeedDoc(
        slug="founding-paper-adler",
        title="LSP Founding Paper — Adler",
        category=Document.Category.FOUNDING,
        filename="LSPFounding PaperAdler.pdf",
        summary="One of the school's founding texts on analyst formation.",
        display_order=20,
    ),
    SeedDoc(
        slug="scholar-formation-founding-text",
        title="Scholar Formation — Founding Text",
        category=Document.Category.FOUNDING,
        filename="LSP Scholar Formation Founding Text 2023-01.pdf",
        summary="Founding text for the scholar formation pathway.",
        display_order=30,
    ),
    # ---- Cartel Resources ----
    SeedDoc(
        slug="five-short-papers-on-the-cartel",
        title="Five Short Papers on the Lacanian Cartel",
        category=Document.Category.CARTEL_RESOURCE,
        filename="Five Short Papers on the Lacanian Cartel.pdf",
        summary="Anthology of short essays on cartel work.",
        display_order=10,
    ),
    SeedDoc(
        slug="work-in-a-cartel",
        title="Work in a Cartel — Desire, Difference, Enigma, and Product",
        category=Document.Category.CARTEL_RESOURCE,
        filename="Work in a Cartel- desire, difference, enigma, & product.pdf",
        summary="An extended essay on what cartel work looks like in practice.",
        display_order=20,
    ),
    SeedDoc(
        slug="cartel-proposal-style-guide",
        title="Style Guide for Cartel Proposals",
        category=Document.Category.CARTEL_RESOURCE,
        filename="Style Sheet for Proposals.pdf",
        summary="Style and format guide for submitting a cartel proposal.",
        display_order=30,
    ),
    # ---- Reference ----
    SeedDoc(
        slug="global-calendar",
        title="LSP Global Calendar",
        category=Document.Category.REFERENCE,
        filename="LSP Global Calendar 2.2025.pdf",
        summary="Annual operational dates for the school.",
        effective_date=date(2025, 2, 1),
        display_order=10,
    ),
]


class Command(BaseCommand):
    help = "Seed initial Documents from ../wix-files/. Idempotent — updates by slug."

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

        created = updated = skipped = 0
        missing: list[str] = []

        for entry in SEED:
            pdf_path = src / entry.filename
            if not pdf_path.is_file():
                missing.append(entry.filename)
                self.stderr.write(self.style.WARNING(f"  missing: {entry.filename}"))
                continue

            existing = Document.objects.filter(slug=entry.slug).first()
            action = "update" if existing else "create"

            if dry_run:
                self.stdout.write(f"  {action}: {entry.slug}  ←  {entry.filename}")
                if existing:
                    updated += 1
                else:
                    created += 1
                continue

            with transaction.atomic():
                doc = existing or Document(slug=entry.slug)
                doc.title = entry.title
                doc.category = entry.category
                doc.summary = entry.summary
                doc.effective_date = entry.effective_date
                doc.display_order = entry.display_order
                doc.visibility = Document.Visibility.PUBLIC
                # Always re-attach the file so a fresh source PDF replaces an
                # older one. The FileField.save call uploads through the
                # configured storage backend.
                with pdf_path.open("rb") as fh:
                    doc.file.save(pdf_path.name, File(fh), save=False)
                doc.save()
                if existing:
                    updated += 1
                    self.stdout.write(f"  updated: {entry.slug}")
                else:
                    created += 1
                    self.stdout.write(self.style.SUCCESS(f"  created: {entry.slug}"))

        skipped = len(missing)
        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write("")
        self.stdout.write(
            f"{prefix}{created} created, {updated} updated, {skipped} missing."
        )
        if missing:
            self.stdout.write(self.style.WARNING("Missing source files:"))
            for name in missing:
                self.stdout.write(f"  - {name}")
