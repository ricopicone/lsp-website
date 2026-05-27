"""Recurrence helper for bulk Session generation (PROG-5).

The helper translates the common faculty-scheduling patterns — "every
Thursday", "first and third Saturdays of Sep–Dec", "these specific
dates" — into a list of concrete ``(start_at, end_at)`` datetime pairs.
Callers (the management command, the admin form) then turn each pair
into a ``Session`` row.

We don't try to model every RFC 5545 RRULE feature. The supported shapes
match the patterns the architecture doc calls out:

- ``weekly``: weekdays only (e.g. every Thursday; every Mon & Wed).
- ``monthly``: ordinal-weekday-of-month (e.g. first and third Saturdays).
- ``dates``: explicit list of dates.

All times are interpreted in the project's configured TIME_ZONE.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time

from dateutil import rrule
from django.utils import timezone

# Map our weekday abbreviations to dateutil constants.
WEEKDAYS = {
    "MO": rrule.MO,
    "TU": rrule.TU,
    "WE": rrule.WE,
    "TH": rrule.TH,
    "FR": rrule.FR,
    "SA": rrule.SA,
    "SU": rrule.SU,
}


@dataclass
class SessionWindow:
    start_at: datetime
    end_at: datetime


def _validate_weekdays(codes: Iterable[str]) -> list:
    out = []
    for c in codes:
        key = c.strip().upper()[:2]
        if key not in WEEKDAYS:
            raise ValueError(
                f"Unknown weekday {c!r}. Expected one of: {', '.join(WEEKDAYS)}."
            )
        out.append(WEEKDAYS[key])
    if not out:
        raise ValueError("At least one weekday is required.")
    return out


def _combine(d: date, t: time) -> datetime:
    return timezone.make_aware(datetime.combine(d, t))


def generate_weekly(
    *,
    start_date: date,
    end_date: date,
    weekdays: Iterable[str],
    start_time: time,
    end_time: time,
) -> list[SessionWindow]:
    """Every occurrence of ``weekdays`` between ``start_date`` and ``end_date``."""
    _check_dates(start_date, end_date, start_time, end_time)
    rule = rrule.rrule(
        freq=rrule.WEEKLY,
        dtstart=datetime.combine(start_date, start_time),
        until=datetime.combine(end_date, end_time),
        byweekday=_validate_weekdays(weekdays),
    )
    return [
        SessionWindow(
            start_at=_combine(dt.date(), start_time),
            end_at=_combine(dt.date(), end_time),
        )
        for dt in rule
    ]


def generate_monthly_ordinal(
    *,
    start_date: date,
    end_date: date,
    weekdays: Iterable[str],
    week_positions: Iterable[int],
    start_time: time,
    end_time: time,
) -> list[SessionWindow]:
    """Ordinal weekdays of each month — e.g. ``week_positions=[1, 3], weekdays=['SA']``
    yields the first and third Saturdays of every month in the range.
    Negative positions count from the end (``-1`` = last)."""
    _check_dates(start_date, end_date, start_time, end_time)
    positions = list(week_positions)
    if not positions:
        raise ValueError("At least one week_position is required.")
    if any(p == 0 or p < -5 or p > 5 for p in positions):
        raise ValueError("week_positions must be in -5..-1 or 1..5 (1=first, -1=last).")
    rule = rrule.rrule(
        freq=rrule.MONTHLY,
        dtstart=datetime.combine(start_date, start_time),
        until=datetime.combine(end_date, end_time),
        byweekday=_validate_weekdays(weekdays),
        bysetpos=positions,
    )
    return [
        SessionWindow(
            start_at=_combine(dt.date(), start_time),
            end_at=_combine(dt.date(), end_time),
        )
        for dt in rule
    ]


def generate_explicit(
    *,
    dates: Iterable[date],
    start_time: time,
    end_time: time,
) -> list[SessionWindow]:
    """An explicit list of dates, all with the same start/end time."""
    if end_time <= start_time:
        raise ValueError("end_time must be after start_time.")
    out = []
    for d in dates:
        out.append(
            SessionWindow(
                start_at=_combine(d, start_time),
                end_at=_combine(d, end_time),
            )
        )
    return out


def _check_dates(start_date: date, end_date: date, start_time: time, end_time: time) -> None:
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date.")
    if end_time <= start_time:
        raise ValueError("end_time must be after start_time.")
