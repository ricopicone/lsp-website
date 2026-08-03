"""Payment-plan schedule reading (task #494).

An approved tuition payment plan is a *schedule*, not a set of obligations:
the year is one annual ``Charge`` however the member chooses to pay it, and
``TuitionInstallment`` rows only split that one debt into payable chunks
(see the ``payment-plan-is-manual-stripe-not-autopay`` project memory for why
splitting the charge would break the promotion gate).

Nothing here mints or moves money. It answers one question — *what does this
plan owe right now?* — for the three surfaces that ask it: the tuition
reminder (nudges on it), the balance reminder (spares members current on it),
and the treasurer's Accounts marker (labels it).
"""

from __future__ import annotations

from datetime import date, timedelta

from .models import TuitionEnrollment, TuitionInstallment, TuitionPeriod

#: How far ahead of its due date an installment starts being nudged. Matched
#: to the weekly reminder cadence so every installment gets at least one
#: nudge *before* it is late rather than only after.
LEAD_DAYS = 7


class State:
    """A plan's standing. Not a model field — derived on read."""

    REQUESTED = "requested"     # applied; the Board hasn't decided
    CURRENT = "current"         # approved, nothing due
    OVERDUE = "overdue"         # approved, an installment is past due


PLAN_STATUSES = (
    TuitionEnrollment.Status.PLAN_REQUESTED,
    TuitionEnrollment.Status.PAYMENT_PLAN,
)


def due_installment(enrollment, today: date, *, lead_days: int = LEAD_DAYS):
    """The unpaid installment needing attention, or ``None``.

    The oldest overdue one wins; failing that, the earliest one falling due
    within ``lead_days``. Ordering by due date (not sequence) means a
    treasurer's hand-edited schedule still reads correctly.
    """
    return (
        enrollment.installments
        .filter(paid=False, due_date__lte=today + timedelta(days=lead_days))
        .order_by("due_date", "sequence")
        .first()
    )


def plan_states(today: date) -> dict[int, str]:
    """Map ``user_id -> State`` for everyone on a plan in the current period.

    Batched — two queries total, never one per member, because the treasurer's
    Accounts table reads this for every row. Members not on a plan are absent
    from the map rather than carrying a null state.
    """
    period = TuitionPeriod.current(on_date=today)
    if period is None:
        return {}

    enrollments = list(
        TuitionEnrollment.objects.filter(
            tuition_period=period, status__in=PLAN_STATUSES,
        ).values("id", "user_id", "status")
    )
    plan_enrollments = {
        e["id"]: e["user_id"] for e in enrollments
        if e["status"] == TuitionEnrollment.Status.PAYMENT_PLAN
    }
    overdue_ids = set(
        TuitionInstallment.objects.filter(
            enrollment_id__in=plan_enrollments.keys(),
            paid=False, due_date__lte=today,
        ).values_list("enrollment_id", flat=True).distinct()
    )

    states: dict[int, str] = {}
    for e in enrollments:
        if e["status"] == TuitionEnrollment.Status.PLAN_REQUESTED:
            states[e["user_id"]] = State.REQUESTED
    for eid, user_id in plan_enrollments.items():
        # An approved plan with no schedule chosen yet is CURRENT: nothing is
        # late, because nothing is scheduled.
        states[user_id] = State.OVERDUE if eid in overdue_ids else State.CURRENT
    return states
