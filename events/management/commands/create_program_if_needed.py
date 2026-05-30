"""Idempotent: ensure Program rows exist for the current + next academic years.

Mirrors create_dues_period_if_needed and create_tuition_period_if_needed.
New programs are created unpublished — the Program Committee publishes
them (or schedules publication via publish_date) when the program for that
year is ready to announce.

Safe to run repeatedly. Wire into the same daily systemd timer as the
dues + tuition rollover commands.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import Program


class Command(BaseCommand):
    help = "Ensure Program rows exist for the current and next academic years."

    def handle(self, *args, **options):
        today = timezone.now().date()
        # The academic year starts in September. If we're past Sept 1 of
        # this calendar year, we're in <thisyear>-<thisyear+1>.
        if today.month >= 9:
            current_start = today.year
        else:
            current_start = today.year - 1
        next_start = current_start + 1

        for start_year in (current_start, next_start):
            self._ensure_program(start_year)

    def _ensure_program(self, start_year: int):
        ay = f"{start_year}-{start_year + 1}"
        existing = Program.objects.filter(academic_year=ay).first()
        if existing is not None:
            self.stdout.write(f"Program {ay} exists; skipping.")
            return
        new = Program.objects.create(
            academic_year=ay,
            name=f"Program {ay}",
            published=False,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {new} (unpublished — Program Committee can publish "
                f"or schedule a publish_date when ready)."
            )
        )
