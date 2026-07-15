"""Unified member-ledger math (task #439).

One account per member: :class:`~payments.models.Charge` rows are the debits,
succeeded non-donation :class:`~payments.models.Payment` rows the credits.
Everything here is a *read-time derivation* from those two sets — one pot of
money swept across OPEN charges oldest-first. There are deliberately no
allocation rows and no stored per-charge paid flags (the #437 lesson:
per-payment-to-year attribution is untenable for this data).
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models.functions import Coalesce

from .models import Charge, DuesPeriod, Payment, TuitionEnrollment

# In-training members owe this many years of tuition total (skipping defers,
# it doesn't reduce the count). Never obligate beyond it.
TUITION_YEARS_REQUIRED = 4

#: Payment statuses/types that count toward the pot.
def _counts(payment: Payment) -> bool:
    return (
        payment.status == Payment.Status.SUCCEEDED
        and payment.payment_type != Payment.Type.DONATION
    )


def _charge_states(open_charges, paid: Decimal) -> dict[int, str]:
    """Sweep the pot across OPEN charges (pre-sorted oldest-first) →
    ``{charge_id: "paid" | "partial" | "unpaid"}``."""
    remaining = paid
    states = {}
    for c in open_charges:
        covered = min(c.amount, remaining)
        remaining -= covered
        states[c.id] = (
            "paid" if covered >= c.amount
            else "partial" if covered > 0 else "unpaid"
        )
    return states


def member_account(user) -> dict:
    """The member's full account: statement lines, balance, category sums."""
    charges = list(
        Charge.objects.filter(user=user)
        .exclude(status=Charge.Status.VOID)
        .select_related("dues_period", "tuition_period", "registration__event")
        .order_by("effective_date", "id")
    )
    open_charges = [c for c in charges if c.status == Charge.Status.OPEN]
    payments = list(
        Payment.objects.filter(user=user)
        .select_related("registration__event")
        .order_by(Coalesce("paid_at", "created_at").asc(), "id")
    )
    paid = sum((p.amount for p in payments if _counts(p)), Decimal("0"))
    obligation = sum((c.amount for c in open_charges), Decimal("0"))
    states = _charge_states(open_charges, paid)

    # Statement: charges and payments merged chronologically with a running
    # balance. WAIVED charges and non-counting payments appear with delta 0.
    lines = []
    for c in charges:
        delta = c.amount if c.status == Charge.Status.OPEN else Decimal("0")
        lines.append({
            "kind": "charge", "obj": c, "date": c.effective_date,
            "delta": delta, "counts": c.status == Charge.Status.OPEN,
            "state": states.get(c.id),
        })
    for p in payments:
        when = (p.paid_at or p.created_at).date()
        counts = _counts(p)
        lines.append({
            "kind": "payment", "obj": p, "date": when,
            "delta": -p.amount if counts else Decimal("0"),
            "counts": counts, "state": None,
        })
    lines.sort(key=lambda ln: (ln["date"], 0 if ln["kind"] == "charge" else 1,
                               ln["obj"].pk))
    running = Decimal("0")
    for ln in lines:
        running += ln["delta"]
        ln["running"] = running

    total_tuition_paid = sum(
        (p.amount for p in payments
         if _counts(p) and p.payment_type == Payment.Type.TUITION),
        Decimal("0"),
    )
    tuition_years_covered = sum(
        1 for c in open_charges
        if c.category == Charge.Category.TUITION and states[c.id] == "paid"
    )

    # Per-year tuition decisions with the charge's sweep state. A non-skipping
    # enrollment with no non-void charge is beyond the 4-year cap → "met".
    charge_by_tp = {c.tuition_period_id: c for c in charges
                    if c.category == Charge.Category.TUITION and c.tuition_period_id}
    enrollments = list(
        TuitionEnrollment.objects.filter(user=user)
        .select_related("tuition_period")
        .order_by("-tuition_period__start_date")
    )
    tuition_rows = []
    skipping = []
    for e in enrollments:
        if e.status == TuitionEnrollment.Status.SKIPPING:
            state = "skipping"
            skipping.append(e.tuition_period)
        else:
            c = charge_by_tp.get(e.tuition_period_id)
            if c is None:
                state = "met"
            elif c.status == Charge.Status.WAIVED:
                state = "waived"
            else:
                state = states.get(c.id, "unpaid")
        tuition_rows.append({
            "enrollment": e, "period": e.tuition_period,
            "rate": e.tuition_period.tuition_amount or Decimal("0"),
            "state": state,
        })

    current_dues = DuesPeriod.current()
    dues_state = None
    if current_dues is not None:
        dc = next((c for c in charges
                   if c.category == Charge.Category.DUES
                   and c.dues_period_id == current_dues.id), None)
        if dc is not None:
            dues_state = ("waived" if dc.status == Charge.Status.WAIVED
                          else states.get(dc.id, "unpaid"))

    balance = obligation - paid
    return {
        "lines": lines,
        "obligation": obligation,
        "paid": paid,
        "balance": balance,
        "owes": max(balance, Decimal("0")),
        "credit": max(-balance, Decimal("0")),
        "total_tuition_paid": total_tuition_paid,
        "tuition_years_covered": tuition_years_covered,
        "tuition_years_required": TUITION_YEARS_REQUIRED,
        "tuition_rows": tuition_rows,
        "dues_state": dues_state,
        "current_dues_period": current_dues,
        "charge_states": states,
        "conflict": balance < 0 and bool(skipping),
    }
