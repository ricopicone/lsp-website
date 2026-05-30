"""Idempotent: always keep current + next academic year set up for tuition.

Mirrors create_dues_period_if_needed. Wired into the same daily systemd
timer. Maintains *two* years ahead at all times so the treasurer and
Program Committee can plan ahead.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from payments.models import TuitionPeriod


class Command(BaseCommand):
    help = (
        "Ensure TuitionPeriod rows exist for the current and next academic years."
    )

    def handle(self, *args, **options):
        today = timezone.now().date()
        if today.month >= 9:
            current_start = today.year
        else:
            current_start = today.year - 1
        next_start = current_start + 1

        for start_year in (current_start, next_start):
            self._ensure_period(start_year)

    def _ensure_period(self, start_year: int):
        slug = f"ay-{start_year}-{start_year + 1}-tuition"
        existing = TuitionPeriod.objects.filter(slug=slug).first()
        if existing is not None:
            self.stdout.write(f"{existing.name} exists; skipping.")
            return

        prior = (
            TuitionPeriod.objects
            .filter(start_date__lt=date(start_year, 9, 1))
            .order_by("-start_date")
            .first()
        )
        if prior is not None:
            amount = prior.tuition_amount
            interval = prior.reminder_interval_days
        else:
            amount = Decimal(str(settings.TUITION_ANNUAL_AMOUNT))
            interval = 7

        new = TuitionPeriod.objects.create(
            name=f"AY {start_year}–{start_year + 1}",
            slug=slug,
            start_date=date(start_year, 9, 1),
            decision_due_date=date(start_year, 9, 30),
            end_date=date(start_year + 1, 8, 31),
            tuition_amount=amount,
            reminder_interval_days=interval,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {new.name} — ${new.tuition_amount}, "
                f"reminders every {interval} days."
            )
        )
