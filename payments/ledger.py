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

from django.db.models import Q
from django.db.models.functions import Coalesce

from .models import Charge, DuesPeriod, Payment, TuitionEnrollment, TuitionPeriod

# In-training members owe this many years of tuition total (skipping defers,
# it doesn't reduce the count). Never obligate beyond it.
TUITION_YEARS_REQUIRED = 4

#: Which payments count toward the pot: succeeded, and not a donation
#: (donations are gifts, not credit against what a member owes).
#:
#: Defined once as a matched pair — ``COUNTING_PAYMENTS`` for querysets,
#: :func:`_counts` for rows already in memory. Change one, change the other;
#: ``test_ledger.py`` asserts they agree over every status × type combination.
COUNTING_PAYMENTS = Q(status=Payment.Status.SUCCEEDED) & ~Q(
    payment_type=Payment.Type.DONATION)


def _counts(payment: Payment) -> bool:
    return (
        payment.status == Payment.Status.SUCCEEDED
        and payment.payment_type != Payment.Type.DONATION
    )


def _charge_states(open_charges, paid: Decimal) -> tuple[dict[int, str], dict[int, Decimal]]:
    """Sweep the pot across OPEN charges (pre-sorted oldest-first).

    Returns ``({charge_id: "paid" | "partial" | "unpaid"}, {charge_id:
    covered_amount})`` — the covered amounts let callers report the
    *uncovered* slice of a charge without replaying the sweep themselves.
    """
    remaining = paid
    states, covered_by_id = {}, {}
    for c in open_charges:
        covered = min(c.amount, remaining)
        remaining -= covered
        covered_by_id[c.id] = covered
        states[c.id] = (
            "paid" if covered >= c.amount
            else "partial" if covered > 0 else "unpaid"
        )
    return states, covered_by_id


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
    states, covered_by_id = _charge_states(open_charges, paid)

    # Statement: charges and payments merged chronologically with a running
    # balance. WAIVED charges and non-counting payments appear with delta 0.
    lines = []
    for c in charges:
        delta = c.amount if c.status == Charge.Status.OPEN else Decimal("0")
        covered = covered_by_id.get(c.id)
        lines.append({
            "kind": "charge", "obj": c, "date": c.effective_date,
            "delta": delta, "counts": c.status == Charge.Status.OPEN,
            "state": states.get(c.id),
            "covered": covered,
            "uncovered": None if covered is None else c.amount - covered,
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
    # Tuition-only overage for the skipping-conflict heuristic. Skipping is a
    # tuition concept — dues and registration fees are owed regardless — so the
    # cross-category balance must not drive this flag (#437's original,
    # tuition-scoped semantics).
    tuition_obligation = sum(
        (c.amount for c in open_charges
         if c.category == Charge.Category.TUITION),
        Decimal("0"),
    )
    tuition_overpaid = max(total_tuition_paid - tuition_obligation, Decimal("0"))

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
        # The Decision column shows the recorded decision — except that a
        # fully covered year reads as its outcome: "Paid" (the record itself
        # is never auto-flipped; sweep coverage can shift as history firms up).
        if state == "paid" and e.status in (
            TuitionEnrollment.Status.COMMITTED,
            TuitionEnrollment.Status.PAYMENT_PLAN,
        ):
            decision_label = "Paid"
        else:
            decision_label = e.get_status_display()
        tuition_rows.append({
            "enrollment": e, "period": e.tuition_period,
            "rate": e.tuition_period.tuition_amount or Decimal("0"),
            "state": state, "decision_label": decision_label,
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
        "tuition_overpaid": tuition_overpaid,
        "tuition_rows": tuition_rows,
        "dues_state": dues_state,
        "current_dues_period": current_dues,
        "charge_states": states,
        "charge_covered": covered_by_id,
        "conflict": tuition_overpaid > 0 and bool(skipping),
    }


def accounts_overview() -> list[dict]:
    """Every member's standing, batched: all non-void charges + per-user paid
    sums fetched up front, then the same sweep as ``member_account`` in
    Python. Rows sorted most-owed first, then by name."""
    from collections import defaultdict

    from django.contrib.auth import get_user_model
    from django.db.models import Max, Sum

    User = get_user_model()

    charges_by_user = defaultdict(list)
    for c in (
        Charge.objects.exclude(status=Charge.Status.VOID)
        .order_by("effective_date", "id")
    ):
        charges_by_user[c.user_id].append(c)

    paid_by_user: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    last_by_user: dict[int, object] = {}
    for row in (
        Payment.objects.filter(COUNTING_PAYMENTS, user__isnull=False)
        .values("user")
        .annotate(s=Sum("amount"), last=Max(Coalesce("paid_at", "created_at")))
    ):
        paid_by_user[row["user"]] = row["s"] or Decimal("0")
        last_by_user[row["user"]] = row["last"]

    # Tuition-only paid sums — the skipping-conflict heuristic is tuition-
    # scoped (see member_account), never the cross-category balance.
    tuition_paid_by_user: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in (
        Payment.objects.filter(
            status=Payment.Status.SUCCEEDED, user__isnull=False,
            payment_type=Payment.Type.TUITION,
        )
        .values("user")
        .annotate(s=Sum("amount"))
    ):
        tuition_paid_by_user[row["user"]] = row["s"] or Decimal("0")

    skipping_users = set(
        TuitionEnrollment.objects.filter(
            status=TuitionEnrollment.Status.SKIPPING,
        ).values_list("user_id", flat=True)
    )

    current_dues = DuesPeriod.current()
    user_ids = set(charges_by_user) | set(paid_by_user)
    users = {
        u.id: u
        for u in User.objects.filter(
            id__in=user_ids, profile__is_persona=False,
        ).select_related("profile")
    }

    rows = []
    for uid in user_ids:
        user = users.get(uid)
        if user is None:
            continue
        charges = charges_by_user.get(uid, [])
        open_charges = [c for c in charges if c.status == Charge.Status.OPEN]
        paid = paid_by_user.get(uid, Decimal("0"))
        obligation = sum((c.amount for c in open_charges), Decimal("0"))
        states, _covered = _charge_states(open_charges, paid)
        balance = obligation - paid
        tuition_obligation = sum(
            (c.amount for c in open_charges
             if c.category == Charge.Category.TUITION),
            Decimal("0"),
        )
        tuition_overpaid = max(
            tuition_paid_by_user.get(uid, Decimal("0")) - tuition_obligation,
            Decimal("0"),
        )
        dues_state = None
        if current_dues is not None:
            dc = next((c for c in charges
                       if c.category == Charge.Category.DUES
                       and c.dues_period_id == current_dues.id), None)
            if dc is not None:
                dues_state = ("waived" if dc.status == Charge.Status.WAIVED
                              else states.get(dc.id, "unpaid"))
        rows.append({
            "user": user,
            "obligation": obligation,
            "paid": paid,
            "balance": balance,
            "owes": max(balance, Decimal("0")),
            "credit": max(-balance, Decimal("0")),
            "tuition_covered": sum(
                1 for c in open_charges
                if c.category == Charge.Category.TUITION and states[c.id] == "paid"
            ),
            "dues_state": dues_state,
            "last_payment": last_by_user.get(uid),
            "tuition_overpaid": tuition_overpaid,
            "conflict": tuition_overpaid > 0 and uid in skipping_users,
        })
    rows.sort(key=lambda r: (-r["balance"], r["user"].last_name or "",
                             r["user"].first_name or "", r["user"].email))
    return rows


def collected_this_ay(today=None) -> dict:
    """Succeeded payments received inside the current AY window, by category."""
    from django.db.models import Sum
    from django.utils import timezone

    on = today or timezone.now().date()
    period = DuesPeriod.current(on) or TuitionPeriod.current(on)
    if period is None:
        return {"window": None, "by_category": {}, "total": Decimal("0")}
    window = (period.start_date, period.end_date)
    by_cat: dict[str, Decimal] = {}
    total = Decimal("0")
    qs = (
        Payment.objects.filter(status=Payment.Status.SUCCEEDED)
        .annotate(when=Coalesce("paid_at", "created_at"))
        .filter(when__date__gte=window[0], when__date__lte=window[1])
        .values("payment_type")
        .annotate(s=Sum("amount"))
    )
    for row in qs:
        by_cat[row["payment_type"]] = row["s"] or Decimal("0")
        total += by_cat[row["payment_type"]]
    return {"window": window, "by_category": by_cat, "total": total}


def tuition_decision_exempt(user) -> bool:
    """Four non-skipping years on record, or four years fully paid — either
    way, no fifth-year decision nag. The 4-year cap means a fifth year never
    mints a charge, so asking for a skip/committed status past that point is
    noise (Rico, 2026-07-16).

    A member can reach four years two ways: four non-skipping
    ``TuitionEnrollment`` rows (the usual, decision-by-decision path), or
    four years' worth of tuition charges already fully paid off with no
    enrollment decisions at all (e.g. minted from approved pre-records
    history submissions for a member who started before the site tracked
    enrollments — task #439 review finding #2). Paid-in-full implies the
    member has met the requirement, so it would be a contradiction to still
    show them an annual decision form. This reuses the same payment-based
    sweep as the "requirement met" badge (``tuition_years_covered >=
    tuition_years_required`` in :func:`member_account`) — which is why
    paid-but-owed is different: a member can be decision-exempt via
    enrollments alone with money still owed on those years; that money is
    chased through the ledger, not through decision reminders."""
    from .models import TuitionEnrollment

    if TuitionEnrollment.objects.filter(user=user).exclude(
        status=TuitionEnrollment.Status.SKIPPING,
    ).count() >= TUITION_YEARS_REQUIRED:
        return True
    acct = member_account(user)
    return acct["tuition_years_covered"] >= acct["tuition_years_required"]


def decision_exempt_ids(rows=None) -> set[int]:
    """:func:`tuition_decision_exempt` for the whole roster at once.

    Same two paths, batched: four non-skipping ``TuitionEnrollment`` rows
    (one aggregate query), or four tuition years covered by the sweep (read
    off :func:`accounts_overview`, which the caller has usually already
    computed — pass it in as ``rows`` to avoid recomputing it).
    """
    from django.db.models import Count

    exempt = set(
        TuitionEnrollment.objects
        .exclude(status=TuitionEnrollment.Status.SKIPPING)
        .values("user")
        .annotate(n=Count("id"))
        .filter(n__gte=TUITION_YEARS_REQUIRED)
        .values_list("user", flat=True)
    )
    if rows is None:
        rows = accounts_overview()
    exempt |= {
        r["user"].id for r in rows
        if r["tuition_covered"] >= TUITION_YEARS_REQUIRED
    }
    return exempt


def tuition_clearance(user) -> list[str]:
    """Reasons a member's tuition standing blocks promotion to Analyst/Scholar.

    Empty list = clear. Necessary-but-insufficient: completing the Passage /
    Traversée remains the Meeting of Analysts' decision — this is only the
    financial criterion (spec 2026-07-16). Personas are exempt. No override
    flag exists: settling the ledger (record payment / adjust / waive / void)
    is the override.
    """
    profile = getattr(user, "profile", None)
    if profile is None or profile.is_persona:
        return []
    acct = member_account(user)
    reasons = []
    # Report the uncovered slice of every OPEN tuition charge, straight off
    # the account's own oldest-first sweep (no second replay here).
    for ln in acct["lines"]:
        if ln["kind"] != "charge" or not ln["counts"]:
            continue  # payments, waived charges: no obligation to cover
        c = ln["obj"]
        if c.category != Charge.Category.TUITION:
            continue
        uncovered = ln["uncovered"]
        if uncovered > 0:
            where = (f"{c.tuition_period.name} tuition charge"
                     if c.tuition_period_id else "A tuition charge")
            reasons.append(f"{where} has ${uncovered} uncovered.")
    if acct["tuition_years_covered"] < acct["tuition_years_required"]:
        reasons.append(
            f"{acct['tuition_years_covered']} of "
            f"{acct['tuition_years_required']} tuition years covered.")
    return reasons


def period_for_event(event):
    """The TuitionPeriod an event belongs to.

    Annual-program events anchor to their start_date; undated or one-off
    events fall back to the period containing today (matching the old
    behavior for special events and Days of Assembly).
    """
    anchor = getattr(event, "start_date", None)
    return TuitionPeriod.current(on_date=anchor)  # anchor=None -> today
