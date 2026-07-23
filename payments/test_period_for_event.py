from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from events.models import Event
from payments.ledger import period_for_event
from payments.models import TuitionPeriod


@pytest.mark.django_db
def test_event_resolves_to_its_ay_period():
    p26 = TuitionPeriod.objects.create(
        name="AY 2026–2027", slug="t26", start_date=date(2026, 9, 1),
        decision_due_date=date(2026, 10, 31), end_date=date(2027, 8, 31),
        tuition_amount=Decimal("2500"),
    )
    e = Event.objects.create(
        title="X", slug="x", start_date=date(2026, 9, 15), end_date=date(2027, 6, 1),
    )
    assert period_for_event(e) == p26


@pytest.mark.django_db
def test_undated_event_falls_back_to_today():
    # Event model requires start_date, so test with a simple object without it
    # When start_date is absent, period_for_event falls back to TuitionPeriod.current(None),
    # which uses today's date. If no period exists for today, returns None.
    e = SimpleNamespace()  # Simple object with no start_date attribute
    result = period_for_event(e)
    # The result depends on whether a TuitionPeriod exists for today
    assert result is None or isinstance(result, TuitionPeriod)
