"""An election's phase is computed from its dates and step stamps (task #813)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from elections.models import Election

pytestmark = pytest.mark.django_db
PT = ZoneInfo("America/Los_Angeles")
T0 = datetime(2026, 11, 1, 9, 0, tzinfo=PT)


def _election(**kw):
    defaults = dict(
        title="Board election 2026", slug="board-2026", seats=3,
        nominations_open_at=T0, nominations_close_at=T0 + timedelta(days=14),
        voting_open_at=T0 + timedelta(days=21), voting_close_at=T0 + timedelta(days=35),
        results_due=(T0 + timedelta(days=42)).date(),
    )
    defaults.update(kw)
    return Election.objects.create(**defaults)


@pytest.mark.parametrize("offset,phase", [
    (timedelta(seconds=-1), Election.Phase.DRAFT),
    (timedelta(0), Election.Phase.NOMINATING),
    (timedelta(days=14, seconds=-1), Election.Phase.NOMINATING),
    (timedelta(days=14), Election.Phase.REVIEW),
    (timedelta(days=30), Election.Phase.REVIEW),  # never VOTING without a slate
])
def test_phase_before_slate(offset, phase):
    assert _election().phase_at(T0 + offset) == phase


def test_phase_after_slate():
    e = _election(slate_published_at=T0 + timedelta(days=15))
    assert e.phase_at(T0 + timedelta(days=16)) == Election.Phase.SLATE
    assert e.phase_at(T0 + timedelta(days=21)) == Election.Phase.VOTING
    assert e.phase_at(T0 + timedelta(days=35)) == Election.Phase.CLOSED


def test_late_slate_opens_voting_on_publication():
    e = _election(slate_published_at=T0 + timedelta(days=25))
    assert e.phase_at(T0 + timedelta(days=25)) == Election.Phase.VOTING


def test_terminal_stamps_win():
    e = _election(slate_published_at=T0, counted_at=T0 + timedelta(days=36))
    assert e.phase_at(T0 + timedelta(days=40)) == Election.Phase.COUNTED
    e.results_published_at = T0 + timedelta(days=37)
    assert e.phase_at(T0 + timedelta(days=40)) == Election.Phase.PUBLISHED
    e2 = _election(slug="b2", acclaimed_at=T0 + timedelta(days=16))
    assert e2.phase_at(T0 + timedelta(days=17)) == Election.Phase.ACCLAIMED


def test_evening_pacific_instant_is_same_day():
    # 17:30 Pacific is 00:30 UTC the next day; the phase compares aware
    # datetimes, never dates, so the evening before the close is still open.
    close = datetime(2026, 11, 15, 18, 0, tzinfo=PT)
    e = _election(nominations_close_at=close)
    assert e.phase_at(datetime(2026, 11, 15, 17, 30, tzinfo=PT)) == Election.Phase.NOMINATING


def test_role_seeded():
    from core.models import StaffRole
    role = StaffRole.objects.get(key=StaffRole.ELECTION_ADMINISTRATOR)
    assert role.name == "Election Administrator"
