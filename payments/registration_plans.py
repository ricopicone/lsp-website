"""Registration payment-plan schedules (task #501).

The sibling of :mod:`payments.plans`, which answers the same questions for a
tuition enrollment. Kept separate rather than generalized: the two share a
shape, not a caller, and unifying them would rewrite the tuition plumbing
shipped in task #494 for no behavior gain.

Nothing here mints or moves money. A plan never changes what is owed — the
registration keeps its full ``quoted_amount`` and mints one full-fee
``Charge`` — these rows only split that one debt into payable chunks.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal

from django.db.models import Sum
from django.utils import timezone

from .models import RegistrationInstallment

#: How far ahead of its due date an installment starts being nudged. Matched
#: to :data:`payments.plans.LEAD_DAYS` so a member on both a tuition plan and
#: an event plan is nudged on the same rhythm.
LEAD_DAYS = 7

#: Closest two installments may ever fall. Spreading three payments across a
#: four-week workshop would put them a fortnight apart, which is a direct debit
#: rather than a payment plan; below this the schedule simply goes monthly.
MIN_INTERVAL_DAYS = 28

CENT = Decimal("0.01")


def build_schedule(
    registration, count: int, *, today: date | None = None,
) -> list[RegistrationInstallment]:
    """Create the installment rows for ``registration``, or return the
    existing ones.

    Even split with the rounding remainder on the **final** installment, so
    the schedule sums to the fee exactly.

    **Payments are spread across the event's own run**, not dropped monthly
    from registration: the span from today to the event's end is divided into
    ``count`` equal periods and a payment falls at the start of each. On the
    common Sept–May seminar that puts two payments in fall and spring, four at
    two-and-two, and nine at monthly — the schedules the school already thinks
    in, without naming any of them. Named terms were rejected precisely because
    they cannot describe the real program's four-week October workshop or its
    January–June reading group.

    The last payment therefore lands inside the event's run: the school is paid
    before it finishes delivering. :data:`MIN_INTERVAL_DAYS` floors the gap, so
    a short event degrades to monthly rather than to a fortnightly debit, and
    an event with no end date (or one already over) is monthly outright.

    Idempotent — a registration that already carries a schedule keeps it,
    whatever ``count`` says.

    Returns ``[]`` for a degenerate request (fewer than two installments, or a
    non-positive fee); those are the ordinary pay-in-full path, not a plan.
    """
    existing = list(registration.installments.order_by("sequence"))
    if existing:
        return existing
    if count < 2:
        return []
    total = Decimal(registration.quoted_amount)
    if total <= 0:
        return []

    today = today or timezone.localdate()
    interval = _interval_days(registration, count, today)
    each = (total / count).quantize(CENT, rounding=ROUND_DOWN)
    rows = [
        RegistrationInstallment(
            registration=registration,
            sequence=i,
            due_date=today + timedelta(days=interval * (i - 1)),
            amount=(each if i < count else total - each * (count - 1)),
        )
        for i in range(1, count + 1)
    ]
    return RegistrationInstallment.objects.bulk_create(rows)


def _interval_days(registration, count: int, today: date) -> int:
    """Days between installments: the event's remaining span divided into
    ``count`` periods, never below :data:`MIN_INTERVAL_DAYS`."""
    end = getattr(registration.event, "end_date", None)
    span = (end - today).days if end else 0
    return max(span // count, MIN_INTERVAL_DAYS)


def is_on_plan(registration) -> bool:
    """Whether this registration is being paid in installments.

    Any schedule at all means a plan: :func:`build_schedule` never writes
    fewer than two rows.

    Reads ``.all()`` rather than ``.exists()`` on purpose — the roster surfaces
    call this per row, and ``.all()`` uses a ``prefetch_related("installments")``
    cache where ``.exists()`` would fire a query anyway. Uncached it is still
    one query for at most twelve tiny rows.
    """
    return bool(registration.installments.all())


def next_unpaid(registration) -> RegistrationInstallment | None:
    """The earliest unpaid installment, regardless of due date — what a member
    pays next, including paying ahead."""
    return registration.installments.filter(paid=False).order_by("sequence").first()


def due_installment(
    registration, today: date, *, lead_days: int = LEAD_DAYS,
) -> RegistrationInstallment | None:
    """The unpaid installment needing attention, or ``None``.

    The oldest overdue one wins; failing that, the earliest one falling due
    within ``lead_days``. Ordering by due date (not sequence) means a
    treasurer's hand-edited schedule still reads correctly — the same rule
    :func:`payments.plans.due_installment` uses.
    """
    return (
        registration.installments
        .filter(paid=False, due_date__lte=today + timedelta(days=lead_days))
        .order_by("due_date", "sequence")
        .first()
    )


def outstanding(registration) -> Decimal:
    """Sum of the unpaid installments. Zero when there is no plan.

    Quantized to cents because ``Sum`` hands back an unscaled Decimal — a
    $200.00 balance arrives as ``Decimal("200")`` and would render as "$200"
    beside its own "$166.66" installments.
    """
    total = registration.installments.filter(paid=False).aggregate(
        total=Sum("amount"),
    )["total"]
    return (total or Decimal("0")).quantize(CENT)
