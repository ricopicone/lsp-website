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

#: The explanation a re-billed registration carries. Doubles as the marker
#: ``unbill_skipped_coverage`` matches on, so no model field is needed.
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

    today = timezone.now().date()
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


def unbill_skipped_coverage(user, period) -> list:
    """Undo ``bill_skipped_coverage`` for rows still unpaid.

    Restores coverage pricing when the member records a paying decision, so
    committing to pay tuition returns their access without any money moving. A
    row the member actually paid is left alone: that is a refund conversation
    for the treasurer, never a silent unwind.
    """
    from payments.ledger import period_for_event
    from registrations.models import Registration

    if period is None:
        return []
    today = timezone.now().date()
    changed = []
    rows = (
        Registration.objects
        .filter(
            user=user,
            quoted_explanation=REBILLED_EXPLANATION,
            status__in=(
                Registration.Status.AWAITING_PAYMENT,
                Registration.Status.PENDING_APPROVAL,
            ),
        )
        .select_related("event", "price_tier")
    )
    for reg in rows:
        if period_for_event(reg.event) != period:
            continue
        reg.quoted_amount = Decimal("0")
        reg.quoted_explanation = COVERED_EXPLANATION
        if reg.status == Registration.Status.AWAITING_PAYMENT:
            reg.status = Registration.Status.PAID
        reg.staff_notes = (
            f"{reg.staff_notes}\n[{today}] Coverage restored for "
            f"{period.name}: tuition is being paid again (task #485)."
        ).strip()
        reg.save(update_fields=(
            "quoted_amount", "quoted_explanation", "status", "staff_notes",
        ))
        changed.append(reg)
    return changed
