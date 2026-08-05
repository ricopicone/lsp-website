"""Shared registration staff operations (REG-14).

One home for side-effect chains used by both the Django admin and the
Registration Admin console, so they cannot drift.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from payments import notifications as notify_payments

from .models import Registration


def apply_resolution(registration, code, resolution):
    """Reprice an awaiting-payment registration under a resolved pricing code.

    Shared by the member's own code box and the auto-apply below, so the two
    cannot drift. Consumes a use, builds a plan schedule when the code carries
    one, settles the registration when the price lands at zero, and expires any
    open Checkout session — the pre-code fee must stop being payable from a tab
    left open, or the member is charged for a place they now hold cheaper.
    """
    from events.models import PricingCode
    from payments import registration_plans
    from payments.stripe_sync import expire_open_sessions

    with transaction.atomic():
        registration.quoted_amount = resolution.amount
        registration.quoted_explanation = resolution.explanation
        registration.pricing_code = code
        if resolution.amount <= Decimal("0"):
            registration.status = Registration.Status.PAID
        registration.save(update_fields=(
            "quoted_amount", "quoted_explanation", "pricing_code", "status",
        ))
        if code.max_uses is not None:
            PricingCode.objects.filter(pk=code.pk).update(
                uses_remaining=F("uses_remaining") - 1
            )
        if resolution.installments > 1 and resolution.amount > 0:
            registration_plans.build_schedule(
                registration, resolution.installments,
            )

    expire_open_sessions(
        registration,
        reason=f"Repriced by code {code.code}; checkout expired.",
    )
    if registration.status == Registration.Status.PAID:
        notify_payments.registration_confirmed(registration)


def pinned_code_for(registration):
    """A redeemable code minted *for this member* on this event, or None."""
    from events.models import PricingCode

    if registration.status != Registration.Status.AWAITING_PAYMENT:
        return None
    for code in PricingCode.objects.filter(
        event_id=registration.event_id,
        restricted_to_user_id=registration.user_id,
    ).order_by("-created_at"):
        if code.is_redeemable(user=registration.user):
            return code
    return None


def auto_apply_pinned_code(registration):
    """Apply a code addressed to this member, when doing so asks nothing of them.

    A convener who pinned a code to a person has already decided; making them
    type it back is pure ceremony. But only where the outcome needs no choice:

    - **a lower price** — unambiguously in their favour, applied;
    - **a payment plan** — changes *when* they pay, so it stays an offer (the
      confirmation page exists precisely so they see a schedule before
      committing to it);
    - **a sliding floor** — they have to name their own amount;
    - **a higher price** — never.

    Returns the code applied, or ``None``.
    """
    from events.pricing import PricingError, resolve_price

    code = pinned_code_for(registration)
    if code is None:
        return None
    try:
        resolution = resolve_price(
            user=registration.user, tier=registration.price_tier,
            pricing_code=code,
        )
    except PricingError:
        return None      # sliding floor, or otherwise needs an input
    if resolution.installments > 1:
        return None      # a schedule is a decision, not a discount
    if resolution.amount >= registration.quoted_amount:
        return None
    apply_resolution(registration, code, resolution)
    return code


def comp_registration(reg, by, *, via: str = "admin") -> tuple[bool, bool]:
    """Comp an awaiting-payment registration (REG-14).

    Flips to COMPED, appends the dated ``staff_notes`` audit line, mints the
    comped ledger charge, and sends the confirmation (with access info).
    Returns ``(comped, email_ok)`` — ``comped`` False when the row wasn't in
    ``AWAITING_PAYMENT``; ``email_ok`` False when the status flip succeeded
    but the notification raised.
    """
    if reg.status != Registration.Status.AWAITING_PAYMENT:
        return False, True
    reg.status = Registration.Status.COMPED
    reg.staff_notes = (reg.staff_notes or "") + (
        f"\n[{timezone.now().date().isoformat()}] Comped by {by.email} via {via}."
    )
    reg.save(update_fields=("status", "staff_notes"))
    from payments.charges import mint_comped_charge
    mint_comped_charge(reg)
    try:
        notify_payments.registration_confirmed(reg)
    except Exception:
        return True, False
    return True, True
