"""Charge minting (task #439).

Idempotent syncs that materialize obligation rows. Two hard rules, both from
the design spec:

- A sync only manages rows it minted; it NEVER modifies a row a treasurer has
  touched (``staff_adjusted=True``). Disagreements surface via
  :func:`tuition_charge_conflicts` on the Reconcile tab instead of clobbering.
- Every automated path keeps a manual override (do-not-over-automate) —
  add/adjust/waive/void actions live on the treasurer member page.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.utils import timezone

from accounts.models import Source

from .models import Charge, Payment

logger = logging.getLogger(__name__)


def sync_dues_charges(period) -> int:
    """Mint one OPEN dues charge per obligated member for ``period``.

    Refuses future periods (rollover maintains current+next AY — next year's
    members must not show as owing early). Returns the number created.
    """
    from .dues import obligated_users_qs

    today = timezone.localdate()
    if period.start_date > today:
        return 0
    have = set(
        Charge.objects.filter(
            category=Charge.Category.DUES, dues_period=period,
        )
        .exclude(status=Charge.Status.VOID)
        .values_list("user_id", flat=True)
    )
    created = 0
    for user in obligated_users_qs().select_related("profile"):
        if user.id in have:
            continue
        amount = period.amount_for_role(user.profile.role)
        if amount is None:
            continue
        Charge.objects.create(
            user=user,
            category=Charge.Category.DUES,
            amount=amount,
            effective_date=period.start_date,
            dues_period=period,
            source=Source.VERIFIED,
            notes=f"[{today}] Minted from the {period.name} dues tier table.",
        )
        created += 1
    return created


def _owed_periods(enrollments) -> dict[int, object]:
    """Map ``tuition_period_id -> enrollment`` for the years a member actually
    owes: non-skipping enrollments oldest-first, capped at
    ``TUITION_YEARS_REQUIRED``. ``enrollments`` must already be ordered
    oldest-first by period start date. The expected rate for an owed year is
    ``enrollment.tuition_period.tuition_amount`` — derive it at the call site.
    """
    from payments.ledger import TUITION_YEARS_REQUIRED

    from .models import TuitionEnrollment

    owed: dict[int, object] = {}
    counted = 0
    for e in enrollments:
        if e.status == TuitionEnrollment.Status.SKIPPING:
            continue
        counted += 1
        if counted > TUITION_YEARS_REQUIRED:
            continue                        # beyond the cap — never owed
        owed[e.tuition_period_id] = e
    return owed


def sync_tuition_charges(user) -> None:
    """Recompute ``user``'s tuition charges from their enrollment decisions.

    Mints/revives/voids only sync-managed rows (``staff_adjusted=False``).

    Applies only to in-training members: transitioning to Analyst/Scholar
    certifies the tuition requirement was completed, so a transitioned
    member's tuition history is FROZEN — never minted, voided, revived, or
    flagged. Reconstruction of pre-records history is the
    ``reconcile_transitioned_tuition`` command's job.
    """
    from accounts.models import Profile

    from .models import TuitionEnrollment

    profile = getattr(user, "profile", None)
    if profile is None or profile.role not in Profile.IN_TRAINING_ROLES:
        return
    if profile.standing in Profile.NON_MEMBER_STANDINGS or profile.deceased_on:
        return  # removed / resigned / deceased — never mint new tuition

    today = timezone.localdate()
    enrollments = list(
        TuitionEnrollment.objects.filter(user=user)
        .select_related("tuition_period")
        .order_by("tuition_period__start_date")
    )
    should = _owed_periods(enrollments)     # tuition_period_id -> enrollment

    existing: dict[int, Charge] = {}        # prefer a non-VOID row per period
    for c in Charge.objects.filter(
        user=user, category=Charge.Category.TUITION, tuition_period__isnull=False,
    ).order_by("id"):
        prev = existing.get(c.tuition_period_id)
        if prev is None or (prev.status == Charge.Status.VOID
                            and c.status != Charge.Status.VOID):
            existing[c.tuition_period_id] = c

    for pid, e in should.items():
        rate = e.tuition_period.tuition_amount or Decimal("0")
        c = existing.get(pid)
        if c is None:
            Charge.objects.create(
                user=user,
                category=Charge.Category.TUITION,
                amount=rate,
                effective_date=e.tuition_period.start_date,
                tuition_period=e.tuition_period,
                source=e.source,
                notes=f"[{today}] Minted from the {e.tuition_period.name} "
                      "enrollment decision.",
            )
            continue
        if c.staff_adjusted:
            continue                        # conflicts surface at read time
        changed = []
        if c.status == Charge.Status.VOID:
            c.status = Charge.Status.OPEN
            changed.append("status")
            c.add_note("Revived — year re-entered the tuition requirement.",
                       save=False)
            changed.append("notes")
        if c.amount != rate:
            c.amount = rate
            changed.append("amount")
        if changed:
            c.save(update_fields=set(changed))

    for pid, c in existing.items():
        if pid in should or c.staff_adjusted or c.status == Charge.Status.VOID:
            continue
        c.status = Charge.Status.VOID
        c.add_note("Voided — year is skipping or beyond the 4-year requirement.",
                   save=False)
        c.save(update_fields=("status", "notes"))


def tuition_charge_conflicts() -> list[dict]:
    """Staff-adjusted tuition charges that disagree with the enrollment-derived
    expectation. Batched for the Reconcile tab."""
    from collections import defaultdict

    from .models import TuitionEnrollment

    enrollments_by_user = defaultdict(list)
    for e in TuitionEnrollment.objects.select_related("tuition_period").order_by(
        "tuition_period__start_date",
    ):
        enrollments_by_user[e.user_id].append(e)

    expected: dict[tuple[int, int], Decimal] = {}   # (user_id, period_id) -> rate
    for uid, enrs in enrollments_by_user.items():
        for pid, e in _owed_periods(enrs).items():
            expected[(uid, pid)] = e.tuition_period.tuition_amount or Decimal("0")

    from accounts.models import Profile

    out = []
    staff_rows = (
        Charge.objects.filter(
            category=Charge.Category.TUITION, staff_adjusted=True,
            tuition_period__isnull=False,
        )
        .select_related("user__profile", "tuition_period")
    )
    for c in staff_rows:
        # Transitioned members' tuition history is frozen (see
        # sync_tuition_charges) — no expectations, so nothing to conflict.
        if c.user.profile.role not in Profile.IN_TRAINING_ROLES:
            continue
        rate = expected.get((c.user_id, c.tuition_period_id))
        if rate is None and c.status == Charge.Status.OPEN:
            out.append({
                "user": c.user, "charge": c, "expected_rate": None,
                "problem": "Open charge for a year that is skipping or beyond "
                           "the 4-year requirement (not owed).",
            })
        elif rate is not None and c.status != Charge.Status.OPEN:
            out.append({
                "user": c.user, "charge": c, "expected_rate": rate,
                "problem": f"Year is owed (rate ${rate}) but the charge is "
                           f"{c.get_status_display().lower()}.",
            })
        elif rate is not None and c.amount != rate:
            out.append({
                "user": c.user, "charge": c, "expected_rate": rate,
                "problem": f"Amount ${c.amount} differs from the year's rate ${rate}.",
            })
    return out


def mint_registration_charge(payment) -> Charge | None:
    """Mint the settled-registration charge alongside its payment.

    Minting at settle time (not at registration creation) means abandoned
    checkouts never create account debt. Idempotent per registration.
    """
    if not payment.registration_id or payment.amount <= 0:
        return None
    existing = (
        Charge.objects.filter(registration_id=payment.registration_id)
        .exclude(status=Charge.Status.VOID)
        .first()
    )
    if existing is not None:
        return existing

    from .registration_plans import is_on_plan

    registration = payment.registration
    # A payment plan pays one debt in chunks: the school billed the whole fee,
    # so that is what the ledger records. Without this a $500 seminar paid in
    # three would enter the books as a $166.66 obligation (task #501). Scoped
    # to plan registrations so no ordinary row's provenance shifts.
    amount = (
        registration.quoted_amount if is_on_plan(registration)
        else payment.amount
    )
    user_id = payment.user_id or payment.registration.user_id
    when = payment.paid_at or timezone.now()
    return Charge.objects.create(
        user_id=user_id,
        category=Charge.Category.REGISTRATION,
        amount=amount,
        effective_date=when.date(),
        registration_id=payment.registration_id,
        source=(Source.VERIFIED if payment.method == Payment.Method.STRIPE
                else Source.STAFF),
        notes=f"[{when.date()}] Minted from payment #{payment.pk} at settle.",
    )


def mint_dues_charge(payment) -> Charge | None:
    """Mint the dues charge alongside an early dues payment (task #625).

    ``sync_dues_charges`` refuses a period that has not started, deliberately —
    next year's members must not read as owing before the year opens. But a
    member who *chose* to pay early is not next year's members: without a
    charge their money sits as loose dues credit until September, which is
    exactly the reading that has confused members before. So the obligation is
    minted by the money arriving rather than by the calendar, the same way
    ``mint_registration_charge`` mints at settle instead of at registration.

    Idempotent against the sync (and itself): a non-void dues charge for the
    year is returned untouched, so the two paths can never double-mint. The
    amount is the year's tier rate, not what was paid — a part payment does
    not shrink the obligation. Restricted to members the sync would itself
    have minted for, so a voluntary payment from a non-obligated member stays
    a credit rather than becoming a debt they never owed.
    """
    from .dues import is_dues_obligated

    period = payment.dues_period
    if period is None or payment.amount <= 0 or payment.user_id is None:
        return None
    existing = (
        Charge.objects.filter(
            user_id=payment.user_id,
            category=Charge.Category.DUES,
            dues_period=period,
        )
        .exclude(status=Charge.Status.VOID)
        .first()
    )
    if existing is not None:
        return existing
    if not is_dues_obligated(payment.user):
        return None
    amount = period.amount_for_role(payment.user.profile.role)
    if amount is None:
        return None
    today = timezone.localdate()
    return Charge.objects.create(
        user_id=payment.user_id,
        category=Charge.Category.DUES,
        amount=amount,
        effective_date=period.start_date,
        dues_period=period,
        source=(Source.VERIFIED if payment.method == Payment.Method.STRIPE
                else Source.STAFF),
        notes=f"[{today}] Minted from payment #{payment.pk} at settle "
              f"({period.name}).",
    )


def mint_comped_charge(registration) -> Charge | None:
    """A comp is a waived charge — the comped value shows on the statement."""
    if not registration.quoted_amount or registration.quoted_amount <= 0:
        return None
    existing = (
        Charge.objects.filter(registration=registration)
        .exclude(status=Charge.Status.VOID)
        .first()
    )
    if existing is not None:
        return existing
    today = timezone.localdate()
    return Charge.objects.create(
        user_id=registration.user_id,
        category=Charge.Category.REGISTRATION,
        amount=registration.quoted_amount,
        effective_date=today,
        registration=registration,
        status=Charge.Status.WAIVED,
        source=Source.STAFF,
        notes=f"[{today}] Comped registration — charge waived at mint.",
    )


def void_registration_charge(registration, reason: str) -> None:
    """Void any non-void charges for the registration (cancel/refund keeps
    the books square)."""
    # Deliberately includes staff_adjusted rows, unlike the sync-safety rule
    # elsewhere in this module — a cancel/refund actually moves money back,
    # so even a treasurer-touched charge must be voided to keep the books
    # square. This is the one intentional exception.
    for c in Charge.objects.filter(registration=registration).exclude(
        status=Charge.Status.VOID,
    ):
        c.status = Charge.Status.VOID
        c.add_note(reason, save=False)
        c.save(update_fields=("status", "notes"))


def waive_open_charges(user, *, reason: str, by=None) -> int:
    """Waive every OPEN charge on ``user``'s account (dues / tuition /
    registration), writing an audited note on each. Idempotent — WAIVED/VOID
    rows are left untouched. Returns the number of charges waived.

    Used when a member is marked Deceased (auto) or Removed (via the treasurer
    one-click action). Waiving is audit-only; it never moves money.
    """
    note = f"{reason} (waived by {by.email})" if by is not None else reason
    n = 0
    for c in Charge.objects.filter(user=user, status=Charge.Status.OPEN):
        c.status = Charge.Status.WAIVED
        c.add_note(note, save=False)
        c.save(update_fields=("status", "notes"))
        n += 1
    return n
