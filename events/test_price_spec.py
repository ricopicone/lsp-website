"""One shared definition of an event's price (task #532)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from events.models import Audience, Event, PriceTier, Session
from events.price_spec import (
    PriceSpec,
    UnrepresentablePricing,
    apply_to_event,
    from_event,
    is_representable,
    label,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def event():
    today = dt.date.today()
    return Event.objects.create(
        title="Priced", slug="priced-event", event_type=Event.Type.SEMINAR,
        start_date=today, end_date=today + dt.timedelta(days=30),
    )


def test_fee_type_is_derived_from_the_amounts():
    assert PriceSpec().fee_type == "free"
    assert PriceSpec(amount=Decimal("500")).fee_type == "fixed"
    assert PriceSpec(sliding_max=Decimal("100")).fee_type == "sliding"
    assert PriceSpec(sliding_min=Decimal("0")).fee_type == "sliding"


@pytest.mark.parametrize("spec", [
    PriceSpec(amount=Decimal("500"), tuition_covers=True),
    PriceSpec(amount=Decimal("50"), tuition_covers=False),
    PriceSpec(sliding_min=Decimal("0"), sliding_max=Decimal("100")),
    PriceSpec(tuition_covers=True),
])
def test_round_trips_through_the_event(event, spec):
    apply_to_event(event, spec)
    assert from_event(event) == spec


@pytest.mark.parametrize("spec", [
    PriceSpec(amount=Decimal("500"), tuition_covers=True),
    PriceSpec(sliding_min=Decimal("0"), sliding_max=Decimal("100")),
    PriceSpec(tuition_covers=False),
])
def test_round_trips_through_json(spec):
    assert PriceSpec.from_dict(spec.to_dict()) == spec


def test_applying_twice_leaves_one_tier(event):
    apply_to_event(event, PriceSpec(amount=Decimal("500")))
    apply_to_event(event, PriceSpec(amount=Decimal("400")))
    assert event.price_tiers.count() == 1
    assert event.price_tiers.get().base_amount == Decimal("400")


def test_free_and_uncovered_creates_no_tier(event):
    """Matches _build_price_tier's 'nothing specified' short-circuit."""
    apply_to_event(event, PriceSpec(tuition_covers=False))
    assert event.price_tiers.count() == 0
    assert from_event(event) == PriceSpec(tuition_covers=False)


def test_a_second_tier_makes_the_event_unrepresentable(event):
    """Safety property 1: never offer an edit that would drop a tier."""
    PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("500"),
        minimum_amount=Decimal("0"),
    )
    PriceTier.objects.create(
        event=event, audience=Audience.STUDENT, base_amount=Decimal("300"),
        minimum_amount=Decimal("0"),
    )
    assert is_representable(event) is False
    assert from_event(event) is None
    with pytest.raises(UnrepresentablePricing):
        apply_to_event(event, PriceSpec(amount=Decimal("100")))
    assert event.price_tiers.count() == 2  # nothing was dropped


def test_a_session_scoped_tier_makes_the_event_unrepresentable(event):
    from django.utils import timezone
    session = Session.objects.create(
        event=event, start_at=timezone.now(),
        end_at=timezone.now() + dt.timedelta(hours=2), sequence=1,
    )
    PriceTier.objects.create(
        event=event, session=session, audience=Audience.ALL,
        base_amount=Decimal("60"), minimum_amount=Decimal("0"),
    )
    assert is_representable(event) is False
    with pytest.raises(UnrepresentablePricing):
        apply_to_event(event, PriceSpec(amount=Decimal("100")))
    assert event.price_tiers.count() == 1


def test_a_non_all_audience_tier_is_unrepresentable(event):
    PriceTier.objects.create(
        event=event, audience=Audience.STUDENT, base_amount=Decimal("300"),
        minimum_amount=Decimal("0"),
    )
    assert is_representable(event) is False
    assert from_event(event) is None


def test_labels():
    assert label(PriceSpec(amount=Decimal("500"), tuition_covers=True)) == (
        "$500, covered by School tuition"
    )
    assert label(PriceSpec(amount=Decimal("50"), tuition_covers=False)) == "$50"
    assert label(PriceSpec(amount=Decimal("62.50"), tuition_covers=False)) == "$62.50"
    assert label(PriceSpec(sliding_min=Decimal("0"), sliding_max=Decimal("100"),
                           tuition_covers=False)) == "Sliding scale $0 to $100"
    assert label(PriceSpec(tuition_covers=False)) == "Free"
