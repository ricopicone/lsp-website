"""Read-only parity report: old per-category numbers vs the unified ledger.

Run on a prod snapshot before cutting the treasurer UI over (spec §4).
Fungibility diffs (dues covered by non-dues money) are EXPECTED — review,
don't panic.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand

from payments import ledger
from payments.models import Charge, Payment, TuitionEnrollment


class Command(BaseCommand):
    help = "Report unified-ledger balances and parity vs the old per-category checks."

    def handle(self, *args, **opts):
        rows = ledger.accounts_overview()

        self.stdout.write("== Balances (nonzero) ==")
        nonzero = [r for r in rows if r["balance"] != 0]
        for r in nonzero:
            tag = f"owes ${r['owes']}" if r["owes"] else f"credit ${r['credit']}"
            self.stdout.write(
                f"  {r['user'].email}: obligation ${r['obligation']}, "
                f"paid ${r['paid']} → {tag}")
        self.stdout.write(f"  ({len(nonzero)} member(s) with a nonzero balance)")

        self.stdout.write("== Dues: ledger vs FK-bound payments ==")
        disagreements = 0
        dues_paid_fk = set(
            Payment.objects.filter(
                payment_type=Payment.Type.DUES,
                status=Payment.Status.SUCCEEDED,
                dues_period__isnull=False, user__isnull=False,
            ).values_list("user_id", "dues_period_id")
        )
        for c in (
            Charge.objects.filter(
                category=Charge.Category.DUES, status=Charge.Status.OPEN,
                dues_period__isnull=False,
            ).select_related("user", "dues_period")
        ):
            acct = ledger.member_account(c.user)
            state = acct["charge_states"].get(c.id, "unpaid")
            fk_paid = (c.user_id, c.dues_period_id) in dues_paid_fk
            if (state == "paid") != fk_paid:
                disagreements += 1
                how = ("covered by the ledger but no FK-bound dues payment"
                       if state == "paid"
                       else "FK-bound dues payment exists but ledger shows "
                            f"{state}")
                self.stdout.write(
                    f"  {c.user.email} / {c.dues_period.name}: {how}")
        self.stdout.write(f"  {disagreements} disagreement(s)")

        self.stdout.write("== Tuition: old #437 formula vs ledger charges ==")
        diffs = 0
        uids = set(TuitionEnrollment.objects.values_list("user_id", flat=True))
        for c_user in sorted(uids):
            enrs = list(
                TuitionEnrollment.objects.filter(user_id=c_user)
                .select_related("tuition_period", "user")
                .order_by("tuition_period__start_date"))
            old_obligation = Decimal("0")
            counted = 0
            for e in enrs:
                if e.status == TuitionEnrollment.Status.SKIPPING:
                    continue
                counted += 1
                if counted > ledger.TUITION_YEARS_REQUIRED:
                    continue
                old_obligation += e.tuition_period.tuition_amount or Decimal("0")
            new_obligation = sum(
                (c.amount for c in Charge.objects.filter(
                    user_id=c_user, category=Charge.Category.TUITION,
                    status=Charge.Status.OPEN)),
                Decimal("0"))
            if old_obligation != new_obligation:
                diffs += 1
                self.stdout.write(
                    f"  {enrs[0].user.email}: enrollment-derived "
                    f"${old_obligation} vs ledger charges ${new_obligation} "
                    "(staff adjustment or missing sync?)")
        self.stdout.write(f"  {diffs} difference(s)")
