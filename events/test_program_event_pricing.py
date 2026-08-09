"""The PC can set an event's price without Django admin (task #532)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from events.models import Audience, Event, PriceTier, Program
from events.price_spec import PriceSpec, from_event

pytestmark = pytest.mark.django_db


@pytest.fixture
def program():
    return Program.objects.create(academic_year="2026-2027", published=True)


def _post_data(**overrides):
    today = dt.date.today()
    data = {
        "title": "New Seminar", "slug": "new-seminar",
        "event_type": Event.Type.SEMINAR,
        "start_date": today.isoformat(),
        "end_date": (today + dt.timedelta(days=90)).isoformat(),
        "format": Event.Format.ONLINE, "status": Event.Status.OPEN,
        "description": "", "readings": "", "schedule_note": "",
        "contact": "", "fee_note": "", "access_info": "",
        "fee_type": "fixed", "fee_amount": "500", "tuition_covers": "on",
    }
    data.update(overrides)
    return data


def test_creating_an_event_mints_its_price_tier(program):
    from events.forms import ProgramEventForm
    form = ProgramEventForm(_post_data(), program=program)
    assert form.is_valid(), form.errors
    event = form.save()
    form.save_price(event)
    assert from_event(event) == PriceSpec(
        amount=Decimal("500"), tuition_covers=True,
    )


def test_sliding_scale_round_trips(program):
    from events.forms import ProgramEventForm
    form = ProgramEventForm(
        _post_data(fee_type="sliding", fee_amount="",
                   fee_sliding_min="0", fee_sliding_max="100"),
        program=program,
    )
    assert form.is_valid(), form.errors
    event = form.save()
    form.save_price(event)
    assert from_event(event) == PriceSpec(
        sliding_min=Decimal("0"), sliding_max=Decimal("100"),
        tuition_covers=True,
    )


def test_a_fixed_fee_needs_an_amount(program):
    from events.forms import ProgramEventForm
    form = ProgramEventForm(
        _post_data(fee_type="fixed", fee_amount=""), program=program,
    )
    assert not form.is_valid()
    assert "fee_amount" in form.errors


def test_sliding_minimum_cannot_exceed_the_maximum(program):
    from events.forms import ProgramEventForm
    form = ProgramEventForm(
        _post_data(fee_type="sliding", fee_amount="",
                   fee_sliding_min="200", fee_sliding_max="100"),
        program=program,
    )
    assert not form.is_valid()
    assert "fee_sliding_min" in form.errors


def test_free_is_accepted_without_any_amount(program):
    from events.forms import ProgramEventForm
    form = ProgramEventForm(
        _post_data(fee_type="free", fee_amount="", tuition_covers=""),
        program=program,
    )
    assert form.is_valid(), form.errors
    event = form.save()
    form.save_price(event)
    assert event.price_tiers.count() == 0


def test_editing_prefills_the_current_price(program):
    from events.forms import ProgramEventForm
    today = dt.date.today()
    event = Event.objects.create(
        title="Existing", slug="existing", event_type=Event.Type.SEMINAR,
        program=program, start_date=today, end_date=today,
    )
    PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("400"),
        minimum_amount=Decimal("0"), covered_by_tuition=True,
    )
    form = ProgramEventForm(instance=event, program=program)
    assert form.initial["fee_type"] == "fixed"
    assert form.initial["fee_amount"] == Decimal("400")
    assert form.initial["tuition_covers"] is True
    assert form.price_readonly is False


def test_a_multi_tier_event_renders_read_only(program):
    """Safety property 1: never offer an edit that would drop a tier."""
    from events.forms import ProgramEventForm
    today = dt.date.today()
    event = Event.objects.create(
        title="Two tiers", slug="two-tiers", event_type=Event.Type.SEMINAR,
        program=program, start_date=today, end_date=today,
    )
    for audience, amount in ((Audience.ALL, "600"), (Audience.STUDENT, "400")):
        PriceTier.objects.create(
            event=event, audience=audience, base_amount=Decimal(amount),
            minimum_amount=Decimal("0"),
        )
    form = ProgramEventForm(instance=event, program=program)
    assert form.price_readonly is True

    bound = ProgramEventForm(
        _post_data(title="Two tiers", slug="two-tiers", fee_amount="1"),
        instance=event, program=program,
    )
    assert bound.is_valid(), bound.errors
    saved = bound.save()
    bound.save_price(saved)
    assert saved.price_tiers.count() == 2
    assert set(saved.price_tiers.values_list("base_amount", flat=True)) == {
        Decimal("600"), Decimal("400"),
    }
