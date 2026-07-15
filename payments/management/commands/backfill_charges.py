"""One-time (idempotent) history minting for the unified ledger (task #439).

Run AFTER deploy, BEFORE cutting the treasurer UI over:

    manage.py backfill_charges --dry-run     # inspect on prod first
    manage.py backfill_charges               # then for real

The --dues-from default (2021-09-01, AY 2021-22) is the earliest year with
decent dues records; adjust after inspecting prod data (Rico decides — spec
allows AY 20-21 or 21-22).
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum
from django.utils import timezone

from accounts.models import Source
from payments.charges import (
    mint_comped_charge,
    mint_registration_charge,
    sync_tuition_charges,
)
from payments.dues import obligated_users_qs
from payments.models import Charge, DuesPeriod, Payment, TuitionEnrollment

User = get_user_model()


class Command(BaseCommand):
    help = "Mint historical Charge rows for the unified member ledger."

    def add_arguments(self, parser):
        parser.add_argument("--dues-from", default="2021-09-01",
                            help="Mint dues charges for periods starting on/after this date.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        self.dry = opts["dry_run"]
        try:
            dues_from = date.fromisoformat(opts["dues_from"])
        except ValueError:
            raise CommandError(
                f"Invalid --dues-from date: {opts['dues_from']!r}"
            ) from None
        if self.dry:
            self.stdout.write("DRY RUN — nothing will be written.")
        self._dues(dues_from)
        self._tuition()
        self._registrations()
        self._pre_ledger_dues_settlement(dues_from)

    def _log(self, msg):
        self.stdout.write(msg)

    def _dues(self, dues_from: date):
        today = timezone.now().date()
        current = DuesPeriod.current()
        periods = DuesPeriod.objects.filter(
            start_date__gte=dues_from, start_date__lte=today,
        ).order_by("start_date")
        for period in periods:
            is_current = current is not None and period.id == current.id
            source = Source.VERIFIED if is_current else Source.ASSUMED
            have = set(
                Charge.objects.filter(
                    category=Charge.Category.DUES, dues_period=period,
                ).exclude(status=Charge.Status.VOID)
                .values_list("user_id", flat=True)
            )
            n = 0
            skipped_joined_later = 0
            for user in obligated_users_qs().select_related("profile"):
                if user.id in have:
                    continue
                yj = user.profile.year_joined
                if yj and yj > period.start_date.year:
                    skipped_joined_later += 1
                    continue  # joined after this AY — no historical debt
                amount = period.amount_for_role(user.profile.role)
                if amount is None:
                    continue
                if not self.dry:
                    Charge.objects.create(
                        user=user, category=Charge.Category.DUES, amount=amount,
                        effective_date=period.start_date, dues_period=period,
                        source=source,
                        notes=f"[{today}] Backfilled from the {period.name} "
                              "tier table (historical role assumed current).",
                    )
                n += 1
            verb = "would mint" if self.dry else "minted"
            line = f"dues {period.name}: {verb} {n} charge(s)"
            if skipped_joined_later:
                line += f", {skipped_joined_later} skipped (joined later)"
            self._log(line)
        self.stdout.write(
            "note: dues passes cover currently-obligated members only (active "
            "standing, dues-obligated role); departed/role-changed members get "
            "no historical charges — treasurer adds those manually if owed."
        )

    def _tuition(self):
        uids = (
            TuitionEnrollment.objects.values_list("user_id", flat=True).distinct()
        )
        n = 0
        for user in User.objects.filter(id__in=list(uids)):
            if not self.dry:
                sync_tuition_charges(user)
            n += 1
        verb = "would sync" if self.dry else "synced"
        self._log(f"tuition: {verb} {n} member(s)")

    def _registrations(self):
        from registrations.models import Registration

        pays = Payment.objects.filter(
            payment_type=Payment.Type.REGISTRATION,
            status=Payment.Status.SUCCEEDED,
            registration__isnull=False,
            amount__gt=0,
        ).select_related("registration")
        n = 0
        for p in pays:
            if not self.dry:
                mint_registration_charge(p)
            n += 1
        comped = Registration.objects.filter(status=Registration.Status.COMPED)
        m = 0
        for reg in comped:
            if not self.dry:
                mint_comped_charge(reg)
            m += 1
        verb = "would process" if self.dry else "processed"
        self._log(f"registrations: {verb} {n} paid + {m} comped")

    def _pre_ledger_dues_settlement(self, dues_from: date):
        """Old dues money (periods before the backfill window) would read as
        phantom credit in the fungible pot — mint matching settled charges."""
        today = timezone.now().date()
        rows = (
            Payment.objects.filter(
                payment_type=Payment.Type.DUES,
                status=Payment.Status.SUCCEEDED,
                dues_period__isnull=False,
                dues_period__start_date__lt=dues_from,
                user__isnull=False,
            )
            .values("user", "dues_period")
            .annotate(s=Sum("amount"))
        )
        n = 0
        for row in rows:
            exists = Charge.objects.filter(
                user_id=row["user"], dues_period_id=row["dues_period"],
            ).exclude(status=Charge.Status.VOID).exists()
            if exists:
                continue
            if not self.dry:
                period = DuesPeriod.objects.get(pk=row["dues_period"])
                Charge.objects.create(
                    user_id=row["user"], category=Charge.Category.DUES,
                    amount=row["s"], effective_date=period.start_date,
                    dues_period=period, source=Source.IMPORTED,
                    notes=f"[{today}] Pre-backfill dues—settled by the matching "
                          "payment(s); minted so old dues money doesn't read "
                          "as credit.",
                )
            n += 1
        verb = "would mint" if self.dry else "minted"
        self._log(f"pre-ledger dues settlements: {verb} {n} charge(s)")
