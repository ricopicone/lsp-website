"""One definition of an event's price (task #532).

The proposal form has always described a price with four values — a fixed
amount, a sliding floor and ceiling, and whether tuition covers it. This module
lifts that description out of the form so the PC's event form, the faculty edit
form, and the change-review loop share it, and so the two event-creation paths
cannot drift apart again. (They had: a proposal minted a complete event while a
PC direct-create minted a bare one with no tier at all.)

**Scope, deliberately narrow.** A spec describes the event-level
``audience=ALL`` tier and nothing else. An event carrying a second tier (a
student rate) or a session-scoped tier is *unrepresentable*: reading it returns
``None`` and writing it raises, rather than quietly reconciling the extra rows
away. Django admin remains the surface for those.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


class UnrepresentablePricing(Exception):
    """The event's tiers are richer than a spec can describe."""


def _dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


@dataclass(frozen=True)
class PriceSpec:
    """What an event costs. ``fee_type`` is derived, never stored."""

    amount: Decimal | None = None
    sliding_min: Decimal | None = None
    sliding_max: Decimal | None = None
    tuition_covers: bool = True

    @property
    def fee_type(self) -> str:
        if self.sliding_min is not None or self.sliding_max is not None:
            return "sliding"
        if self.amount is not None:
            return "fixed"
        return "free"

    def to_dict(self) -> dict:
        """JSON-safe form (Decimals as strings) for EventChangeRequest."""
        return {
            "amount": None if self.amount is None else str(self.amount),
            "sliding_min": (
                None if self.sliding_min is None else str(self.sliding_min)
            ),
            "sliding_max": (
                None if self.sliding_max is None else str(self.sliding_max)
            ),
            "tuition_covers": self.tuition_covers,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> PriceSpec:
        data = data or {}
        return cls(
            amount=_dec(data.get("amount")),
            sliding_min=_dec(data.get("sliding_min")),
            sliding_max=_dec(data.get("sliding_max")),
            tuition_covers=bool(data.get("tuition_covers", True)),
        )


def is_representable(event) -> bool:
    """True when a spec can describe this event's pricing without loss."""
    from .models import Audience

    tiers = list(event.price_tiers.all())
    if len(tiers) > 1:
        return False
    if not tiers:
        return True
    tier = tiers[0]
    return tier.session_id is None and tier.audience == Audience.ALL


def from_event(event) -> PriceSpec | None:
    """The event's current price, or None when it is unrepresentable."""
    if not is_representable(event):
        return None
    tier = event.price_tiers.first()
    if tier is None:
        # No tier means nothing was ever specified, which is the state
        # ``apply_to_event`` produces for a free, uncovered event.
        return PriceSpec(tuition_covers=False)
    if tier.sliding_scale:
        return PriceSpec(
            sliding_min=tier.minimum_amount or Decimal("0"),
            sliding_max=tier.base_amount,
            tuition_covers=tier.covered_by_tuition,
        )
    if tier.base_amount == 0 and tier.covered_by_tuition:
        return PriceSpec(tuition_covers=True)
    return PriceSpec(
        amount=tier.base_amount, tuition_covers=tier.covered_by_tuition,
    )


def apply_to_event(event, spec: PriceSpec) -> None:
    """Reconcile the event's single event-level tier to ``spec``.

    Mirrors what ``EventProposal._build_price_tier`` has always done, including
    its "nothing specified" short-circuit: a free event that tuition does not
    cover carries no tier at all.
    """
    if not is_representable(event):
        raise UnrepresentablePricing(
            f"{event.slug} carries pricing a spec cannot describe; "
            "edit its tiers in Django admin."
        )
    from .models import Audience, PriceTier

    sliding = spec.fee_type == "sliding"
    if not sliding and spec.amount is None and not spec.tuition_covers:
        event.price_tiers.all().delete()
        return

    base = spec.amount
    if base is None:
        base = spec.sliding_max if spec.sliding_max is not None else Decimal("0")

    values = {
        "audience": Audience.ALL,
        "base_amount": base,
        "sliding_scale": sliding,
        "minimum_amount": (
            (spec.sliding_min or Decimal("0")) if sliding else Decimal("0")
        ),
        "covered_by_tuition": spec.tuition_covers,
    }
    tier = event.price_tiers.first()
    if tier is None:
        PriceTier.objects.create(event=event, **values)
    else:
        for field, value in values.items():
            setattr(tier, field, value)
        tier.save(update_fields=list(values))


def _money(value: Decimal) -> str:
    """'$500' for whole dollars, '$62.50' otherwise."""
    value = Decimal(value)
    if value == value.to_integral_value():
        return f"${value.to_integral_value()}"
    return f"${value:.2f}"


def label(spec: PriceSpec) -> str:
    """A short human description, for the review diff and the admin listings."""
    if spec.fee_type == "sliding":
        low = _money(spec.sliding_min or Decimal("0"))
        high = _money(spec.sliding_max or Decimal("0"))
        base = f"Sliding scale {low} to {high}"
    elif spec.fee_type == "fixed":
        base = _money(spec.amount)
    else:
        base = "Free"
    if spec.tuition_covers:
        return f"{base}, covered by School tuition"
    return base
