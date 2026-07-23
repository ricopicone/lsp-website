"""Derive per-year TuitionEnrollment status from recorded tuition payments.

For each member with succeeded tuition payments in an academic year, ensure a
``TuitionEnrollment`` for that year marking it paid: PAID_IN_FULL when their
total for the year covers the period's tuition amount, otherwise PAYMENT_PLAN
(committed + paying). Gives a partial historical record for the back years that
have payments but no enrollment decision on file.

Dry-run by default; ``--commit`` to write. Excludes provisional
(``source=ASSUMED``) tuition by default — the recurring-charge sweep is
unconfirmed — pass ``--include-assumed`` to fold it in. Idempotent: an existing
enrollment is only *upgraded* (never downgraded), and a SKIPPING row is flipped
(a payment contradicts skipping).
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.membership import current_academic_year_start as ay_of
from accounts.models import Source
from payments.models import Payment, TuitionEnrollment, TuitionPeriod

#: Lifecycle ordering — we upgrade toward "more paid", never the reverse.
_RANK = {
    TuitionEnrollment.Status.PLAN_REQUESTED: 0,
    TuitionEnrollment.Status.SKIPPING: 1,
    TuitionEnrollment.Status.COMMITTED: 2,
    TuitionEnrollment.Status.PAYMENT_PLAN: 3,
    TuitionEnrollment.Status.PAID_IN_FULL: 4,
}


class Command(BaseCommand):
    help = "Backfill TuitionEnrollment status from recorded tuition payments."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true",
                            help="Write changes (default: dry-run preview).")
        parser.add_argument("--include-assumed", action="store_true",
                            help="Also derive from provisional (source=ASSUMED) "
                            "tuition payments (the unconfirmed sweep).")

    def handle(self, *args, **opts):
        period_by_ay = {ay_of(p.start_date): p for p in TuitionPeriod.objects.all()}

        qs = Payment.objects.filter(
            payment_type=Payment.Type.TUITION,
            status=Payment.Status.SUCCEEDED,
            user_id__isnull=False, paid_at__isnull=False,
        )
        if not opts["include_assumed"]:
            qs = qs.exclude(source=Source.ASSUMED)

        totals: dict = defaultdict(lambda: Decimal("0"))
        for user_id, paid_at, amount in qs.values_list("user_id", "paid_at", "amount"):
            period = period_by_ay.get(ay_of(paid_at.date()))
            if period is not None:
                totals[(user_id, period.id)] += amount

        periods = {p.id: p for p in period_by_ay.values()}
        created = upgraded = unchanged = 0
        with transaction.atomic():
            for (user_id, period_id), total in totals.items():
                period = periods[period_id]
                derived = (
                    TuitionEnrollment.Status.PAID_IN_FULL
                    if total >= (period.tuition_amount or Decimal("0"))
                    else TuitionEnrollment.Status.PAYMENT_PLAN
                )
                existing = TuitionEnrollment.objects.filter(
                    user_id=user_id, tuition_period=period
                ).first()
                if existing is None:
                    TuitionEnrollment.objects.create(
                        user_id=user_id, tuition_period=period, status=derived,
                        source=Source.IMPORTED,
                        notes="Backfilled from recorded tuition payments.",
                    )
                    created += 1
                elif _RANK[derived] > _RANK[existing.status]:
                    existing.status = derived
                    existing.notes = (
                        (existing.notes + "\n" if existing.notes else "")
                        + "Upgraded from recorded tuition payments (backfill)."
                    )
                    existing.save(update_fields=["status", "notes"])
                    upgraded += 1
                else:
                    unchanged += 1
            if not opts["commit"]:
                transaction.set_rollback(True)

        verb = "Would create" if not opts["commit"] else "Created"
        self.stdout.write(
            f"{verb} {created} enrollment(s); upgraded {upgraded}; "
            f"left {unchanged} unchanged "
            f"(across {len({k[0] for k in totals})} members, "
            f"{len(totals)} member-years)."
        )
        if not opts["commit"]:
            self.stdout.write(self.style.WARNING(
                "Dry run — nothing written. Re-run with --commit to apply."
            ))
        else:
            self.stdout.write(self.style.SUCCESS("Committed."))
