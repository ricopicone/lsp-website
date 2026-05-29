"""Pricing resolver (architecture § 6.2).

Given a user, a price tier, an optional sliding amount, and an optional
pricing code, return the amount due plus a human-readable explanation
(for staff review and audit) and the code used (if any).

This is one of the two places where a bug costs money (the other is the
Stripe webhook handler), so the resolver is a single function with
exhaustive unit tests. Per-class registration in Phase 1 is handled by
calling the resolver once per (session, tier) pair and summing — keeps
this function single-purpose and the tests bounded.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import PriceTier, PricingCode

ZERO = Decimal("0.00")


class PricingError(ValueError):
    """Raised when the inputs to the resolver are inconsistent or invalid."""


@dataclass
class PriceResolution:
    amount: Decimal
    explanation: str
    code_redeemed: PricingCode | None = None


def resolve_price(
    *,
    user,
    tier: PriceTier,
    sliding_amount: Decimal | None = None,
    pricing_code: PricingCode | None = None,
) -> PriceResolution:
    """Resolve the amount a user owes for ``tier``.

    Precedence:

    1. A valid pricing code overrides everything (REG-17).
    2. ``covered_by_tuition`` + tuition-paying member ⇒ zero (REG-4).
    3. Sliding-scale tier requires ``sliding_amount`` ≥ ``minimum_amount`` (REG-5).
    4. Otherwise the tier's ``base_amount``.

    Raises ``PricingError`` on inconsistent inputs (sliding without amount,
    amount below the floor, code from a different event, code not redeemable).
    """
    if pricing_code is not None:
        return _apply_code(pricing_code, user, tier, sliding_amount)

    if tier.covered_by_tuition and _is_tuition_paying(user):
        return PriceResolution(
            amount=ZERO,
            explanation="Covered by tuition (tuition-paying member, REG-4).",
        )

    if tier.sliding_scale:
        if sliding_amount is None:
            raise PricingError("Sliding-scale tier requires a sliding_amount.")
        if sliding_amount < ZERO:
            raise PricingError("sliding_amount cannot be negative.")
        minimum = tier.minimum_amount if tier.minimum_amount is not None else ZERO
        if sliding_amount < minimum:
            raise PricingError(
                f"sliding_amount {sliding_amount} below minimum {minimum}."
            )
        return PriceResolution(
            amount=sliding_amount,
            explanation=f"Sliding scale (min ${minimum}); chose ${sliding_amount}.",
        )

    return PriceResolution(
        amount=tier.base_amount,
        explanation=f"Standard {tier.get_audience_display()} price.",
    )


def _apply_code(
    code: PricingCode,
    user,
    tier: PriceTier,
    sliding_amount: Decimal | None,
) -> PriceResolution:
    if code.event_id != tier.event_id:
        raise PricingError("Pricing code does not apply to this event.")
    if not code.is_redeemable(user=user):
        raise PricingError("Pricing code is not redeemable for this user / time.")

    if code.pricing_mode == PricingCode.Mode.PERCENT_OFF:
        discount = (tier.base_amount * code.amount_or_percent / Decimal("100")).quantize(
            Decimal("0.01")
        )
        amount = max(tier.base_amount - discount, ZERO)
        explanation = (
            f"{code.amount_or_percent}% off ${tier.base_amount} via code {code.code} "
            f"(–${discount})."
        )
    elif code.pricing_mode == PricingCode.Mode.FIXED_AMOUNT:
        amount = code.amount_or_percent
        explanation = f"Fixed price ${amount} via code {code.code}."
    elif code.pricing_mode == PricingCode.Mode.SLIDING_FLOOR:
        # The code sets a minimum; the participant chooses any amount ≥ floor.
        floor = code.amount_or_percent
        if sliding_amount is None:
            raise PricingError(
                f"Code {code.code} is sliding-scale (minimum ${floor}); "
                "enter the amount you'd like to pay."
            )
        if sliding_amount < ZERO:
            raise PricingError("sliding_amount cannot be negative.")
        if sliding_amount < floor:
            raise PricingError(
                f"sliding_amount {sliding_amount} below floor ${floor} "
                f"(code {code.code})."
            )
        amount = sliding_amount
        explanation = (
            f"Sliding scale via code {code.code} (min ${floor}); chose ${amount}."
        )
    else:
        raise PricingError(f"Unknown pricing_mode: {code.pricing_mode!r}")

    return PriceResolution(amount=amount, explanation=explanation, code_redeemed=code)


def _is_tuition_paying(user) -> bool:
    """Whether ``user`` is tuition-current for today's academic year.

    Consults the per-period TuitionEnrollment via Profile.is_tuition_current
    (M7.5). Falls back to the legacy Profile.tuition_paying boolean only when
    no TuitionPeriod is configured for the current date — keeps existing
    behavior intact while tuition periods are being seeded.
    """
    profile = getattr(user, "profile", None)
    if profile is None:
        return False
    if profile.current_tuition_enrollment() is not None:
        return profile.is_tuition_current()
    # No TuitionPeriod row covers today, or no enrollment yet — fall back to
    # the legacy boolean so REG-4 keeps working pre-migration.
    from payments.models import TuitionPeriod
    if TuitionPeriod.current() is None:
        return bool(profile.tuition_paying)
    # Period exists but no enrollment row: explicit no-decision-yet → False.
    return False
