"""Idempotent: ensure a DuesPeriod covers today; create the next AY if not.

Wired into a weekly systemd timer on the EC2 host so the rollover happens
without manual admin intervention. Safe to run repeatedly.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from payments.models import DuesPeriod


class Command(BaseCommand):
    help = "Ensure a DuesPeriod exists covering today; create next AY if needed."

    def handle(self, *args, **options):
        today = timezone.now().date()
        current = DuesPeriod.current(today)
        if current is not None:
            self.stdout.write(f"Current period exists: {current.name}. Nothing to do.")
            return

        last = DuesPeriod.objects.order_by("-start_date").first()
        if last is None:
            # Bootstrap: AY starts Sep 1 of this year if we're past Sep 1, else last.
            start_year = today.year if today.month >= 9 else today.year - 1
            pre_cand  = Decimal(str(settings.DUES_PRE_CANDIDATE_AMOUNT))
            cand      = Decimal(str(settings.DUES_CANDIDATE_AMOUNT))
            analyst   = Decimal(str(settings.DUES_ANALYST_AMOUNT))
        else:
            start_year = last.start_date.year + 1
            pre_cand  = last.dues_amount_pre_candidate
            cand      = last.dues_amount_candidate
            analyst   = last.dues_amount_analyst

        new = DuesPeriod.objects.create(
            name=f"AY {start_year}–{start_year + 1}",
            slug=f"ay-{start_year}-{start_year + 1}",
            start_date=date(start_year, 9, 1),
            due_date=date(start_year, 10, 1),
            end_date=date(start_year + 1, 8, 31),
            dues_amount_pre_candidate=pre_cand,
            dues_amount_candidate=cand,
            dues_amount_analyst=analyst,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {new.name} — runs "
                f"{new.start_date.isoformat()} to {new.end_date.isoformat()}. "
                f"Tiers: pre-cand ${pre_cand} / cand ${cand} / analyst ${analyst}."
            )
        )
