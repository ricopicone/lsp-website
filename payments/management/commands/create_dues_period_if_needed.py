"""Idempotent: always keep current + next academic year set up for dues.

Runs on a daily systemd timer on the EC2 host. Maintains *two* years
ahead at all times so the treasurer and Program Committee can plan
ahead. Each created year inherits its dues tiers and reminder cadence
from the most recent prior year (or settings defaults on first bootstrap).

Safe to run repeatedly.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from payments.models import DuesPeriod


class Command(BaseCommand):
    help = (
        "Ensure DuesPeriod rows exist for the current and next academic years."
    )

    def handle(self, *args, **options):
        today = timezone.now().date()
        # Compute the start years for current + next AYs.
        if today.month >= 9:
            current_start = today.year
        else:
            current_start = today.year - 1
        next_start = current_start + 1

        for start_year in (current_start, next_start):
            self._ensure_period(start_year)

        # Mint this year's dues charges for the unified ledger (task #439).
        from payments.charges import sync_dues_charges
        from payments.models import DuesPeriod as DP

        current = DP.current()
        if current is not None:
            n = sync_dues_charges(current)
            if n:
                self.stdout.write(f"Minted {n} dues charge(s) for {current.name}.")

    def _ensure_period(self, start_year: int):
        slug = f"ay-{start_year}-{start_year + 1}"
        existing = DuesPeriod.objects.filter(slug=slug).first()
        if existing is not None:
            self.stdout.write(f"{existing.name} exists; skipping.")
            return

        # Inherit from the most recent prior period, or fall back to settings
        # for the bootstrap case.
        prior = (
            DuesPeriod.objects
            .filter(start_date__lt=date(start_year, 9, 1))
            .order_by("-start_date")
            .first()
        )
        if prior is not None:
            pre_cand = prior.dues_amount_pre_candidate
            cand     = prior.dues_amount_candidate
            analyst  = prior.dues_amount_analyst
            interval = prior.reminder_interval_days
        else:
            pre_cand = Decimal(str(settings.DUES_PRE_CANDIDATE_AMOUNT))
            cand     = Decimal(str(settings.DUES_CANDIDATE_AMOUNT))
            analyst  = Decimal(str(settings.DUES_ANALYST_AMOUNT))
            interval = 7

        new = DuesPeriod.objects.create(
            name=f"AY {start_year}–{start_year + 1}",
            slug=slug,
            start_date=date(start_year, 9, 1),
            due_date=date(start_year, 10, 1),
            end_date=date(start_year + 1, 8, 31),
            dues_amount_pre_candidate=pre_cand,
            dues_amount_candidate=cand,
            dues_amount_analyst=analyst,
            reminder_interval_days=interval,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {new.name} — "
                f"tiers ${pre_cand} / ${cand} / ${analyst}, "
                f"reminders every {interval} days."
            )
        )
