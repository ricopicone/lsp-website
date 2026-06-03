"""Seed historical dues + tuition periods (for the Stripe/treasurer backfill).

Tuition and dues were constant through AY 24-25 (tuition $2,000; dues
$50 / $100 / $150), stepping to $2,500 tuition only for 25-26 (already on
record). This creates the missing academic-year rows so the treasurer
dashboard, dues obligation, and per-year reporting cover the full history.

Dry-run by default; pass ``--commit`` to write. Idempotent: a period already
covering an academic year is left untouched (and reported, so a mismatched
amount is visible rather than silently overwritten).

    uv run python manage.py seed_historical_periods            # preview
    uv run python manage.py seed_historical_periods --commit
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from payments.models import DuesPeriod, TuitionPeriod


class Command(BaseCommand):
    help = "Seed historical dues + tuition periods (constant amounts through 24-25)."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true",
                            help="Write changes (default: dry-run preview).")
        parser.add_argument("--from-ay", type=int, default=2020,
                            help="First academic-year start year (default 2020).")
        parser.add_argument("--through-ay", type=int, default=2024,
                            help="Last academic-year start year (default 2024).")
        parser.add_argument("--tuition", type=float, default=2000.0,
                            help="Tuition amount for these years (default 2000).")
        parser.add_argument("--dues", default="50,100,150",
                            help="pre,candidate,analyst dues tiers (default 50,100,150).")

    def handle(self, *args, **opts):
        tuition = Decimal(str(opts["tuition"]))
        try:
            pre, cand, analyst = (Decimal(x.strip()) for x in opts["dues"].split(","))
        except (ValueError, ArithmeticError):
            self.stderr.write("--dues must be 'pre,candidate,analyst', e.g. 50,100,150")
            return

        actions: list[str] = []
        with transaction.atomic():
            for year in range(opts["from_ay"], opts["through_ay"] + 1):
                actions.append(self._seed_year(year, tuition, pre, cand, analyst))
            if not opts["commit"]:
                transaction.set_rollback(True)

        self.stdout.write("\n".join(actions))
        if opts["commit"]:
            self.stdout.write(self.style.SUCCESS("Committed."))
        else:
            self.stdout.write(self.style.WARNING(
                "Dry run — nothing written. Re-run with --commit to apply."
            ))

    def _seed_year(self, year, tuition, pre, cand, analyst) -> str:
        start = datetime.date(year, 9, 1)
        end = datetime.date(year + 1, 8, 31)
        label = f"AY {year}–{year + 1}"
        slug = f"ay-{year}-{year + 1}"
        lines = []

        existing_d = DuesPeriod.objects.filter(start_date=start).first()
        if existing_d:
            lines.append(
                f"  dues   {label}: exists "
                f"(${existing_d.dues_amount_pre_candidate}/"
                f"${existing_d.dues_amount_candidate}/"
                f"${existing_d.dues_amount_analyst}) — left as is"
            )
        else:
            DuesPeriod.objects.create(
                name=label, slug=slug, start_date=start, end_date=end,
                due_date=datetime.date(year, 12, 1),
                dues_amount_pre_candidate=pre,
                dues_amount_candidate=cand,
                dues_amount_analyst=analyst,
            )
            lines.append(f"  dues   {label}: create ${pre}/${cand}/${analyst}")

        existing_t = TuitionPeriod.objects.filter(start_date=start).first()
        if existing_t:
            lines.append(
                f"  tuition {label}: exists (${existing_t.tuition_amount}) — left as is"
            )
        else:
            TuitionPeriod.objects.create(
                name=label, slug=slug, start_date=start, end_date=end,
                decision_due_date=datetime.date(year, 10, 1),
                tuition_amount=tuition,
            )
            lines.append(f"  tuition {label}: create ${tuition}")
        return "\n".join(lines)
