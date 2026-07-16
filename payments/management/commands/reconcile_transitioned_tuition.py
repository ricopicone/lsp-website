"""One-time (idempotent) reconstruction of transitioned members' tuition history.

A member who transitioned out of the in-training roles completed the four-year
tuition requirement by definition — often before our records start. Their
enrollment-derived charges therefore overstate history. This command trims
each such member's tuition charges to their RECORDED tuition payments,
oldest charge first:

- fully covered charge  → kept untouched (real history; nets to zero)
- partially covered     → amount trimmed to the covered portion
- fully uncovered       → voided (the year was not actually owed)

Touched rows get ``staff_adjusted=True`` and a dated audit note; the tuition
sync never revisits transitioned members (frozen history), so the result is
stable. Overpayments (e.g. mis-typed seminar money) are deliberately left as
visible credit for the treasurer's re-typing pass. Safe to re-run.

    manage.py reconcile_transitioned_tuition --dry-run   # inspect first
    manage.py reconcile_transitioned_tuition
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum

from accounts.models import Profile
from payments.models import Charge, Payment


class Command(BaseCommand):
    help = ("Trim transitioned (non-in-training) members' tuition charges to "
            "their recorded tuition payments.")

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        if dry:
            self.stdout.write("DRY RUN — nothing will be written.")

        charges_by_user: dict[int, list[Charge]] = {}
        for c in (
            Charge.objects.filter(category=Charge.Category.TUITION)
            .exclude(status=Charge.Status.VOID)
            .select_related("user__profile")
            .order_by("effective_date", "id")
        ):
            profile = c.user.profile
            if profile.role in Profile.IN_TRAINING_ROLES or profile.is_persona:
                continue
            charges_by_user.setdefault(c.user_id, []).append(c)

        kept = trimmed = voided = 0
        for uid, charges in charges_by_user.items():
            user = charges[0].user
            remaining = Payment.objects.filter(
                user_id=uid, payment_type=Payment.Type.TUITION,
                status=Payment.Status.SUCCEEDED,
            ).aggregate(s=Sum("amount"))["s"] or Decimal("0")
            actions = []
            for c in charges:
                covered = min(c.amount, remaining)
                remaining -= covered
                if covered >= c.amount:
                    kept += 1
                    actions.append(f"kept ${c.amount} ({c.tuition_period})")
                    continue
                if covered > 0:
                    trimmed += 1
                    actions.append(
                        f"trim ${c.amount} → ${covered} ({c.tuition_period})")
                    if not dry:
                        c.add_note(
                            f"Trimmed from ${c.amount} to ${covered} — tuition "
                            "requirement completed before records; obligation "
                            "reconstructed to recorded payments.", save=False)
                        c.amount = covered
                        c.staff_adjusted = True
                        c.save(update_fields=("amount", "staff_adjusted", "notes"))
                else:
                    voided += 1
                    actions.append(f"void ${c.amount} ({c.tuition_period})")
                    if not dry:
                        c.add_note(
                            "Voided — tuition requirement completed before "
                            "records; year not actually owed.", save=False)
                        c.status = Charge.Status.VOID
                        c.staff_adjusted = True
                        c.save(update_fields=("status", "staff_adjusted", "notes"))
            self.stdout.write(
                f"{user.email} ({user.profile.role}): " + "; ".join(actions))

        verb = "would be " if dry else ""
        self.stdout.write(
            f"{len(charges_by_user)} member(s): {kept} charge(s) kept, "
            f"{trimmed} {verb}trimmed, {voided} {verb}voided.")
