"""Idempotent: ensure a TuitionPeriod covers today; create the next AY if not.

Mirrors create_dues_period_if_needed. Wired into the same weekly systemd
timer so the academic-year rollover happens without manual intervention.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from payments.models import TuitionPeriod


class Command(BaseCommand):
    help = "Ensure a TuitionPeriod exists covering today; create next AY if needed."

    def handle(self, *args, **options):
        today = timezone.now().date()
        current = TuitionPeriod.current(today)
        if current is not None:
            self.stdout.write(f"Current period exists: {current.name}. Nothing to do.")
            return

        last = TuitionPeriod.objects.order_by("-start_date").first()
        if last is None:
            start_year = today.year if today.month >= 9 else today.year - 1
            amount = Decimal(str(settings.TUITION_ANNUAL_AMOUNT))
        else:
            start_year = last.start_date.year + 1
            amount = last.tuition_amount

        new = TuitionPeriod.objects.create(
            name=f"AY {start_year}–{start_year + 1}",
            slug=f"ay-{start_year}-{start_year + 1}-tuition",
            start_date=date(start_year, 9, 1),
            decision_due_date=date(start_year, 9, 30),
            end_date=date(start_year + 1, 8, 31),
            tuition_amount=amount,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {new.name} (${new.tuition_amount}) — runs "
                f"{new.start_date.isoformat()} to {new.end_date.isoformat()}."
            )
        )
