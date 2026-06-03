"""Read-only sanity audit of the financial data (ledger + Stripe + inferred).

Surfaces things that probably don't make sense — double-counted dues, tuition
that looks like seminars, overpaid years, unattributed money, broken Stripe
integrity, and enrollment/payment mismatches — so they can be fixed before the
survey + reconciliation pass. Writes nothing.

    uv run python manage.py audit_finances            # full report
    uv run python manage.py audit_finances --examples 20
"""

from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Count, Sum

from accounts.membership import current_academic_year_start as ay_of
from accounts.models import Profile, Source
from payments.models import DuesPeriod, Payment, TuitionEnrollment, TuitionPeriod

TAG_RE = re.compile(r"\[stripe-import:([^\]]+)\]")


class Command(BaseCommand):
    help = "Read-only sanity audit of the financial data. Writes nothing."

    def add_arguments(self, parser):
        parser.add_argument("--examples", type=int, default=10,
                            help="Max example rows to show per finding (default 10).")

    def handle(self, *args, **opts):
        self.n = opts["examples"]
        self._overview()
        self._attribution()
        self._stripe_integrity()
        self._dues_sanity()
        self._tuition_sanity()
        self._enrollment_consistency()
        self._provisional_summary()
        self.stdout.write("\n— audit complete (nothing written) —")

    # -- helpers ------------------------------------------------------------

    def _h(self, title):
        self.stdout.write(f"\n{'=' * 4} {title} {'=' * 4}")

    def _finding(self, label, rows, *, money=None):
        n = len(rows)
        flag = "" if n == 0 else "  ⚠"
        extra = f" (${money:,.2f})" if money is not None else ""
        self.stdout.write(f"  {n:>4}{flag}  {label}{extra}")
        for r in rows[: self.n]:
            self.stdout.write(f"        {r}")
        if n > self.n:
            self.stdout.write(f"        … and {n - self.n} more")

    def _who(self, p) -> str:
        if p.user_id:
            return p.user.get_full_name() or p.user.email
        return f"(unmatched) {p.email or '?'}"

    # -- sections -----------------------------------------------------------

    def _overview(self):
        self._h("OVERVIEW")
        succ = Payment.objects.filter(status=Payment.Status.SUCCEEDED)
        for grouping in ("payment_type", "source", "method", "status"):
            self.stdout.write(f"  by {grouping}:")
            base = Payment.objects if grouping == "status" else succ
            for row in (base.values(grouping)
                        .annotate(n=Count("id"), s=Sum("amount"))
                        .order_by("-s")):
                self.stdout.write(
                    f"      {row['n']:>4}  {row[grouping] or '—':<14} "
                    f"${(row['s'] or Decimal('0')):,.2f}"
                )
        total = succ.aggregate(s=Sum("amount"))["s"] or Decimal("0")
        self.stdout.write(f"  TOTAL succeeded: {succ.count()} rows, ${total:,.2f}")

    def _attribution(self):
        self._h("ATTRIBUTION")
        succ = Payment.objects.filter(status=Payment.Status.SUCCEEDED)
        unmatched = list(succ.filter(user__isnull=True).select_related())
        money = sum((p.amount for p in unmatched), Decimal("0"))
        self._finding(
            "succeeded payments with no member linked",
            [f"{p.payment_type} ${p.amount} {p.paid_at:%Y-%m-%d} {p.email or '?'}"
             for p in unmatched],
            money=money,
        )
        orphan = list(succ.filter(user__isnull=True).filter(email=""))
        self._finding(
            "…of those, also no email (un-attributable + no receipt path)",
            [f"{p.payment_type} ${p.amount} {p.paid_at:%Y-%m-%d} {p.notes[:50]}"
             for p in orphan],
        )
        bad_amt = list(succ.filter(amount__lte=0))
        self._finding("succeeded payments with amount ≤ 0",
                      [f"${p.amount} {p.payment_type} {self._who(p)}" for p in bad_amt])
        no_date = list(succ.filter(paid_at__isnull=True))
        self._finding("succeeded payments with no paid_at",
                      [f"${p.amount} {p.payment_type} {self._who(p)}" for p in no_date])

    def _stripe_integrity(self):
        self._h("STRIPE INTEGRITY")
        dup_pi = list(
            Payment.objects.exclude(stripe_payment_intent_id="")
            .values("stripe_payment_intent_id")
            .annotate(n=Count("id")).filter(n__gt=1)
        )
        self._finding("payment_intent ids on more than one Payment",
                      [f"{d['stripe_payment_intent_id']} ×{d['n']}" for d in dup_pi])

        # Charge-tag duplicates (same Stripe charge imported onto >1 row).
        tag_rows = defaultdict(list)
        for pk, notes in Payment.objects.exclude(notes="").values_list("id", "notes"):
            for m in TAG_RE.finditer(notes or ""):
                tag_rows[m.group(1)].append(pk)
        dup_tags = {k: v for k, v in tag_rows.items() if len(v) > 1}
        self._finding("Stripe charge ids tagged on more than one Payment",
                      [f"{cid} → payments {pks}" for cid, pks in dup_tags.items()])

        stripe_no_ids = list(
            Payment.objects.filter(method=Payment.Method.STRIPE,
                                    status=Payment.Status.SUCCEEDED,
                                    stripe_payment_intent_id="",
                                    stripe_checkout_session_id="")
        )
        self._finding("method=stripe succeeded but no Stripe ids",
                      [f"${p.amount} {p.payment_type} {self._who(p)} {p.paid_at:%Y-%m-%d}"
                       for p in stripe_no_ids])

    def _dues_sanity(self):
        self._h("DUES SANITY")
        tiers_by_ay: dict = defaultdict(set)
        for dp in DuesPeriod.objects.all():
            ay = ay_of(dp.start_date)
            tiers_by_ay[ay] |= {dp.dues_amount_pre_candidate, dp.dues_amount_candidate,
                                dp.dues_amount_analyst}

        dues = list(
            Payment.objects.filter(payment_type=Payment.Type.DUES,
                                   status=Payment.Status.SUCCEEDED,
                                   user__isnull=False, paid_at__isnull=False)
            .select_related("user")
        )
        # >1 dues payment for the same member in the same academic year.
        by_user_ay: dict = defaultdict(list)
        for p in dues:
            by_user_ay[(p.user_id, ay_of(p.paid_at.date()))].append(p)
        multi = [(k, v) for k, v in by_user_ay.items() if len(v) > 1]
        self._finding(
            "members with >1 dues payment in one academic year (possible dup)",
            [f"{self._who(v[0])} AY{k[1]}: {len(v)}× = "
             f"${sum((x.amount for x in v), Decimal('0'))}" for k, v in multi],
        )
        # Dues amounts that don't match that year's tiers.
        odd = [p for p in dues
               if tiers_by_ay.get(ay_of(p.paid_at.date()))
               and p.amount not in tiers_by_ay[ay_of(p.paid_at.date())]]
        self._finding("dues payments whose amount matches no tier that year",
                      [f"{self._who(p)} ${p.amount} {p.paid_at:%Y-%m-%d}" for p in odd])
        no_period = list(
            Payment.objects.filter(payment_type=Payment.Type.DUES,
                                   status=Payment.Status.SUCCEEDED,
                                   dues_period__isnull=True)
        )
        self._finding("succeeded dues not linked to a DuesPeriod",
                      [f"{self._who(p)} ${p.amount} {p.paid_at:%Y-%m-%d}" for p in no_period])

    def _tuition_sanity(self):
        self._h("TUITION SANITY")
        amount_by_ay = {ay_of(tp.start_date): tp.tuition_amount
                        for tp in TuitionPeriod.objects.all()}
        tuition = list(
            Payment.objects.filter(payment_type=Payment.Type.TUITION,
                                   status=Payment.Status.SUCCEEDED,
                                   user__isnull=False, paid_at__isnull=False)
            .select_related("user", "user__profile")
        )
        by_user_ay: dict = defaultdict(lambda: Decimal("0"))
        years_by_user: dict = defaultdict(set)
        for p in tuition:
            ay = ay_of(p.paid_at.date())
            by_user_ay[(p.user_id, ay)] += p.amount
            years_by_user[p.user_id].add(ay)

        # Year totals exceeding the year's tuition (overpaid → dup/miscat).
        over = [(k, v) for k, v in by_user_ay.items()
                if amount_by_ay.get(k[1]) and v > amount_by_ay[k[1]]]
        u_by_id = {p.user_id: p.user for p in tuition}
        self._finding(
            "member-years where tuition paid exceeds the year's tuition",
            [f"{(u_by_id[k[0]].get_full_name() or u_by_id[k[0]].email)} "
             f"AY{k[1]}: ${v} > ${amount_by_ay[k[1]]}" for k, v in over],
        )
        # >4 distinct tuition years (tuition is four years — extra looks like seminars).
        many = [(uid, yrs) for uid, yrs in years_by_user.items() if len(yrs) > 4]
        self._finding(
            "members with tuition in >4 academic years (likely seminars-as-tuition)",
            [f"{(u_by_id[uid].get_full_name() or u_by_id[uid].email)}: "
             f"{len(yrs)} years" for uid, yrs in many],
        )
        # Tuition booked to someone who isn't on the tuition track.
        non_track = [p for p in tuition
                     if p.user.profile.role in (
                         Profile.Role.MEMBER, Profile.Role.EXTERNAL,
                         Profile.Role.PROSPECTIVE_APPLICANT)
                     and p.source != Source.ASSUMED]
        self._finding(
            "confident tuition booked to a non-student role (member/auditor)",
            [f"{self._who(p)} ({p.user.profile.get_role_display()}) ${p.amount} "
             f"{p.paid_at:%Y-%m-%d}" for p in non_track],
        )

    def _enrollment_consistency(self):
        self._h("ENROLLMENT ↔ PAYMENT CONSISTENCY")
        amount_by_period = {tp.id: tp.tuition_amount for tp in TuitionPeriod.objects.all()}
        period_by_ay = {ay_of(tp.start_date): tp.id for tp in TuitionPeriod.objects.all()}

        paid_by_user_period: dict = defaultdict(lambda: Decimal("0"))
        for p in Payment.objects.filter(
            payment_type=Payment.Type.TUITION, status=Payment.Status.SUCCEEDED,
            user__isnull=False, paid_at__isnull=False,
        ).values_list("user_id", "paid_at", "amount"):
            pid = period_by_ay.get(ay_of(p[1].date()))
            if pid:
                paid_by_user_period[(p[0], pid)] += p[2]

        paid_in_full_short = []
        for e in (TuitionEnrollment.objects
                  .filter(status=TuitionEnrollment.Status.PAID_IN_FULL)
                  .select_related("user", "tuition_period")):
            paid = paid_by_user_period.get((e.user_id, e.tuition_period_id), Decimal("0"))
            full = amount_by_period.get(e.tuition_period_id) or Decimal("0")
            if paid < full:
                paid_in_full_short.append(
                    f"{e.user.get_full_name() or e.user.email} {e.tuition_period.name}: "
                    f"paid ${paid} < ${full}"
                )
        self._finding("enrollments marked PAID_IN_FULL but payments fall short",
                      paid_in_full_short)

        enrolled = set(
            TuitionEnrollment.objects.values_list("user_id", "tuition_period_id")
        )
        gaps = [k for k in paid_by_user_period if k not in enrolled]
        self._finding(
            "member-years with tuition payments but NO enrollment row (gap)",
            [f"user#{uid} period#{pid}: ${paid_by_user_period[(uid, pid)]}"
             for (uid, pid) in gaps],
        )

    def _provisional_summary(self):
        self._h("PROVISIONAL (source=ASSUMED) — reconciliation backlog")
        assumed = Payment.objects.filter(source=Source.ASSUMED)
        total = assumed.aggregate(s=Sum("amount"))["s"] or Decimal("0")
        self.stdout.write(f"  {assumed.count()} payments, ${total:,.2f} awaiting confirmation")
        for row in (assumed.values("payment_type")
                    .annotate(n=Count("id"), s=Sum("amount")).order_by("-s")):
            self.stdout.write(
                f"      {row['n']:>4}  {row['payment_type']:<14} ${(row['s'] or 0):,.2f}"
            )
        unmatched = assumed.filter(user__isnull=True).count()
        self.stdout.write(f"  of which {unmatched} are unmatched (need a member link)")
