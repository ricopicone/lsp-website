"""What tuition coverage bought a member in an academic year (task #485).

A registration priced at $0 because the member's tuition covers it leaves no
Payment and no Charge — ``mint_registration_charge`` requires a positive amount
— so it is invisible to the ledger. That is correct while the year is being
paid for. It stops being correct the moment the year is skipped: the member
keeps the events for free.

This module answers three questions and nothing else: which registrations
coverage paid for in a period, what each would have cost, and how to bill or
un-bill them. Wiring lives in ``payments.views.tuition_decision``; staff paths
deliberately do not auto-bill (a historical backfill would retro-bill years of
events).
"""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

#: The explanation a tuition-covered registration carries. Matches the string
#: written by ``registrations.views.register_for_event``'s covered short-circuit
#: — keep them identical.
COVERED_EXPLANATION = "Covered by tuition (tuition-paying member, REG-4)."

#: The explanation a re-billed registration carries. Nothing matches on it —
#: ``apply_coverage`` asks the structural question instead (task #561) — but it
#: is what the member and the treasurer read on the row, and a test pins it.
REBILLED_EXPLANATION = (
    "Regular fee: tuition coverage no longer applies (tuition skipped this year)."
)


def retro_amount(tier) -> Decimal:
    """What a covered registration on ``tier`` is worth without coverage.

    A ``covered_by_tuition`` tier is the same tier non-paying members buy, so
    its ``base_amount`` is the regular fee. On a sliding tier the member would
    have chosen their own figure at or above the floor, so assume the floor.
    """
    if tier.sliding_scale:
        return tier.minimum_amount or Decimal("0")
    return tier.base_amount or Decimal("0")


def covered_registrations(user, period) -> list:
    """The member's registrations that tuition coverage paid for in ``period``.

    Excludes comps (already charge-backed by ``mint_comped_charge``),
    pricing-code freebies (not coverage), and anything cancelled or refunded.
    """
    from payments.ledger import period_for_event
    from registrations.models import Registration

    if period is None:
        return []
    rows = (
        Registration.objects
        .filter(
            user=user,
            price_tier__covered_by_tuition=True,
            pricing_code__isnull=True,
            quoted_amount=Decimal("0"),
            status__in=(
                Registration.Status.PAID,
                Registration.Status.PENDING_APPROVAL,
            ),
        )
        .select_related("event", "price_tier")
        .order_by("event__start_date", "pk")
    )
    return [r for r in rows if period_for_event(r.event) == period]


def bill_skipped_coverage(user, period) -> list:
    """Re-quote each covered registration in ``period`` at the regular fee.

    Idempotent — ``covered_registrations`` only returns $0 rows, so a row this
    already billed cannot reappear. Returns the rows changed.
    """
    from registrations.models import Registration

    today = timezone.localdate()
    changed = []
    for reg in covered_registrations(user, period):
        amount = retro_amount(reg.price_tier)
        if amount <= 0:
            continue                     # a free tier owes nothing
        reg.quoted_amount = amount
        reg.quoted_explanation = REBILLED_EXPLANATION
        # Only a PAID row moves. approve() routes a PENDING_APPROVAL row on the
        # amount, so flipping it here would skip the faculty approval it awaits.
        if reg.status == Registration.Status.PAID:
            reg.status = Registration.Status.AWAITING_PAYMENT
        reg.staff_notes = (
            f"{reg.staff_notes}\n[{today}] Re-billed ${amount} for "
            f"{period.name}: tuition skipped, so coverage no longer applies "
            "(task #485)."
        ).strip()
        reg.save(update_fields=(
            "quoted_amount", "quoted_explanation", "status", "staff_notes",
        ))
        changed.append(reg)
    return changed


def apply_coverage(user, period) -> list:
    """Price every unpaid registration ``period``'s tuition covers at $0.

    Called wherever a covering decision is recorded, by the member or by the
    treasurer. It answers "what does coverage owe this member now" rather than
    undoing one specific earlier action, so it reaches both the row
    ``bill_skipped_coverage`` re-billed and the row quoted the regular fee
    because it was created before any covering decision existed (task #561).
    Those two differ only in a string, and matching that string is what left
    the second case unfixable — a re-billed row is a strict subset of what the
    filter below selects.

    A row with money actually on it is excluded by the status filter: a fee
    genuinely paid is a refund conversation for the treasurer, never a silent
    unwind. Returns the rows changed.
    """
    from payments.ledger import period_for_event
    from payments.models import TuitionEnrollment
    from payments.stripe_sync import expire_open_sessions
    from registrations.models import Registration

    if period is None:
        return []
    # Guarded once rather than per row: the loop already pins every candidate
    # to ``period``, so this is ``is_tuition_current`` for all of them in a
    # single query.
    enrollment = TuitionEnrollment.objects.filter(
        user=user, tuition_period=period,
    ).first()
    if not (enrollment and enrollment.covers_seminars):
        return []

    today = timezone.localdate()
    changed = []
    rows = (
        Registration.objects
        .filter(
            user=user,
            price_tier__covered_by_tuition=True,
            pricing_code__isnull=True,
            quoted_amount__gt=Decimal("0"),
            status__in=(
                Registration.Status.AWAITING_PAYMENT,
                Registration.Status.PENDING_APPROVAL,
            ),
        )
        .select_related("event", "price_tier")
        .order_by("event__start_date", "pk")
    )
    for reg in rows:
        if period_for_event(reg.event) != period:
            continue
        # Kill any live Checkout session first. Otherwise a member returning to
        # a stale tab pays for a place they now hold for free, and
        # ``complete_payment``'s settle guard mints no Charge against it, so the
        # money lands as unattributed credit for the treasurer to refund by hand.
        expire_open_sessions(
            reg, reason="Tuition coverage applied — no payment is owed.",
        )
        reg.quoted_amount = Decimal("0")
        reg.quoted_explanation = COVERED_EXPLANATION
        # approve() routes a PENDING_APPROVAL row on the amount, so flipping it
        # here would skip the faculty approval it is waiting for.
        if reg.status == Registration.Status.AWAITING_PAYMENT:
            reg.status = Registration.Status.PAID
        reg.staff_notes = (
            f"{reg.staff_notes}\n[{today}] Covered by tuition for "
            f"{period.name}: a paying decision is on file, so no payment is "
            "owed (task #561)."
        ).strip()
        reg.save(update_fields=(
            "quoted_amount", "quoted_explanation", "status", "staff_notes",
        ))
        changed.append(reg)
    return changed
