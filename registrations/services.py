"""Shared registration staff operations (REG-14).

One home for side-effect chains used by both the Django admin and the
Registration Admin console, so they cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass
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
        f"\n[{timezone.localdate().isoformat()}] Comped by {by.email} via {via}."
    )
    reg.save(update_fields=("status", "staff_notes"))
    from payments.charges import mint_comped_charge
    mint_comped_charge(reg)
    try:
        notify_payments.registration_confirmed(reg)
    except Exception:
        return True, False
    return True, True


def release_pending_approvals(event, by) -> list[Registration]:
    """Approve everything still waiting on an event (task #564).

    Called when ``requires_faculty_approval`` is turned back off. Off has to be
    the inverse of on: otherwise a queue the event no longer has a reason to
    hold keeps nudging the faculty every three days, and clearing it means
    deciding each row by hand to undo what was one checkbox to do.

    Same side-effect chain as ``registrations.views.approve_registration``, so
    the two cannot drift. Returns the rows it released — build any message from
    these rather than from a copy read before the call, which still shows the
    old status. Idempotent: ``approve()`` returns False on a row that is no
    longer pending, so a second pass sends nothing.
    """
    released = []
    for reg in event.registrations.filter(
        status=Registration.Status.PENDING_APPROVAL
    ).select_related("user", "event"):
        if not reg.approve(by):
            continue
        if reg.needs_payment:
            notify_payments.registration_approved(reg)
        else:
            notify_payments.registration_confirmed(reg)
        released.append(reg)
    return released


#: Statuses a registration cannot be removed from — it is already closed.
TERMINAL_STATUSES = (
    Registration.Status.CANCELLED,
    Registration.Status.REFUNDED,
    Registration.Status.DECLINED,
)


@dataclass(frozen=True)
class Removal:
    """What a removal actually did — build messages from this, never from a
    copy of the registration read beforehand (#485, #561, #564)."""

    removed: bool               #: False when the row was already terminal
    refunded: bool              #: a Stripe refund was actually issued
    refunded_amount: Decimal    #: what went back (0 when nothing did)
    left_money: Decimal         #: settled money not refunded (0 when none)


def remove_registration(reg, by, *, refund: bool = False, reason: str = "",
                        via: str = "registration admin") -> Removal:
    """Release a registrant's place (task #627).

    Removing and refunding are two decisions and the caller states both. A
    refund the site cannot issue never blocks the removal: an offline payment,
    a payment plan, or more than one payment all release the place and hand the
    money to the treasurer instead.

    The registration's charge is voided in every case. For a paid row removed
    without a refund that deliberately leaves the member holding credit in the
    registration bucket, which is the honest reading — they paid, the
    obligation is gone — and is the signal the treasurer acts on.
    """
    from payments.charges import void_registration_charge
    from payments.models import Payment

    if reg.status in TERMINAL_STATUSES:
        return Removal(
            removed=False, refunded=False,
            refunded_amount=Decimal("0"), left_money=Decimal("0"),
        )

    # Read the money before the status moves; afterwards the reading changes.
    settled = sum(
        (p.amount for p in reg.payments.filter(status=Payment.Status.SUCCEEDED)),
        Decimal("0"),
    )

    issued = None
    if refund:
        try:
            issued = reg.cancel(refund=True)
        except RuntimeError:
            # RefundError (and PlanRefundRequiresTreasurer, which subclasses
            # it) plus the bare RuntimeError cancel() raises when it can find
            # no Stripe payment to refund. All of them mean the same thing
            # here: the site will not move this money, but the place still
            # goes. cancel() raises inside its atomic block, so nothing was
            # written and the second call starts clean.
            reg.cancel(refund=False)
    else:
        reg.cancel(refund=False)

    refunded = issued is not None
    left = Decimal("0") if refunded else settled

    void_registration_charge(reg, f"Registration removed by {by.email}.")

    if refunded:
        outcome = f"Refunded ${settled}."
    elif left:
        outcome = f"${left} left unrefunded for the treasurer."
    else:
        outcome = "No money had settled."
    line = (
        f"\n[{timezone.localdate().isoformat()}] Removed by {by.email} "
        f"via {via}. {outcome}"
    )
    if reason:
        line += f" Reason: {reason}"
    reg.staff_notes = (reg.staff_notes or "") + line
    reg.save(update_fields=("staff_notes",))

    notify_payments.registration_cancelled(
        reg, refund=issued, reason=reason, staff_removed=True,
    )
    if left:
        notify_payments.removal_left_money(reg, left, by)

    return Removal(
        removed=True, refunded=refunded,
        refunded_amount=settled if refunded else Decimal("0"),
        left_money=left,
    )
