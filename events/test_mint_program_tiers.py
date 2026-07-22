"""mint_program_tiers: fee-note translation, per-session math, idempotency."""

from __future__ import annotations

from datetime import date, datetime
from datetime import timezone as tz
from decimal import Decimal

import pytest
from django.core.management import call_command

from events.models import Event, PriceTier, Session


def _event(slug: str, sessions: int = 0) -> Event:
    e = Event.objects.create(
        title=slug, slug=slug,
        start_date=date(2026, 9, 1), end_date=date(2027, 6, 15),
    )
    for i in range(sessions):
        Session.objects.create(
            event=e,
            start_at=datetime(2026, 10, 1 + i, 18, tzinfo=tz.utc),
            end_at=datetime(2026, 10, 1 + i, 20, tzinfo=tz.utc),
            sequence=i + 1,
        )
    return e


@pytest.mark.django_db
def test_dry_run_writes_nothing():
    _event("intro-to-lacan-basic-concepts-2026-27")
    call_command("mint_program_tiers")
    assert PriceTier.objects.count() == 0


@pytest.mark.django_db
def test_fixed_donation_and_per_session_tiers():
    fixed = _event("intro-to-lacan-basic-concepts-2026-27")
    donation = _event("das-unbehagen-2026-27")
    per_session = _event("beyond-principle-2026-27", sessions=20)
    call_command("mint_program_tiers", "--commit")

    t = fixed.price_tiers.get()
    assert (t.base_amount, t.sliding_scale, t.covered_by_tuition) == (
        Decimal("50"), False, True,
    )
    t = donation.price_tiers.get()
    assert (t.base_amount, t.sliding_scale, t.minimum_amount) == (
        Decimal("100"), True, Decimal("0"),
    )
    t = per_session.price_tiers.get()  # $25 x 20 sessions, none turned away
    assert (t.base_amount, t.sliding_scale, t.minimum_amount) == (
        Decimal("500"), True, Decimal("0"),
    )


@pytest.mark.django_db
def test_rerun_skips_events_with_tiers():
    _event("intro-to-lacan-basic-concepts-2026-27")
    call_command("mint_program_tiers", "--commit")
    call_command("mint_program_tiers", "--commit")
    assert PriceTier.objects.count() == 1
