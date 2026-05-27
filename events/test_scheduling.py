"""Tests for the recurrence helper (events.scheduling, PROG-5)."""

from __future__ import annotations

from datetime import date, time

import pytest
from django.test import override_settings

from events.scheduling import (
    generate_explicit,
    generate_monthly_ordinal,
    generate_weekly,
)


@override_settings(TIME_ZONE="UTC", USE_TZ=True)
def test_weekly_every_thursday_sep_to_dec_2026():
    windows = generate_weekly(
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 15),
        weekdays=["TH"],
        start_time=time(10, 0),
        end_time=time(12, 0),
    )
    # Sep 3, 10, 17, 24; Oct 1, 8, 15, 22, 29; Nov 5, 12, 19, 26; Dec 3, 10 = 15
    assert len(windows) == 15
    assert all(w.start_at.weekday() == 3 for w in windows)  # Thursday
    assert windows[0].start_at.date() == date(2026, 9, 3)
    assert (windows[0].end_at - windows[0].start_at).total_seconds() == 2 * 3600


@override_settings(TIME_ZONE="UTC", USE_TZ=True)
def test_weekly_multiple_weekdays():
    windows = generate_weekly(
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
        weekdays=["MO", "WE"],
        start_time=time(18, 0),
        end_time=time(19, 30),
    )
    # Sep 2026: Mondays 7, 14, 21, 28; Wednesdays 2, 9, 16, 23, 30 = 9
    assert len(windows) == 9


@override_settings(TIME_ZONE="UTC", USE_TZ=True)
def test_monthly_first_and_third_saturdays():
    windows = generate_monthly_ordinal(
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 31),
        weekdays=["SA"],
        week_positions=[1, 3],
        start_time=time(10, 0),
        end_time=time(12, 0),
    )
    # Each month has a first and third Saturday; 4 months × 2 = 8
    assert len(windows) == 8
    dates = [w.start_at.date() for w in windows]
    assert dates[0] == date(2026, 9, 5)   # first Sat of Sep
    assert dates[1] == date(2026, 9, 19)  # third Sat of Sep
    assert dates[-1] == date(2026, 12, 19)


@override_settings(TIME_ZONE="UTC", USE_TZ=True)
def test_monthly_last_friday():
    windows = generate_monthly_ordinal(
        start_date=date(2026, 9, 1),
        end_date=date(2026, 11, 30),
        weekdays=["FR"],
        week_positions=[-1],
        start_time=time(13, 0),
        end_time=time(15, 0),
    )
    assert [w.start_at.date() for w in windows] == [
        date(2026, 9, 25),
        date(2026, 10, 30),
        date(2026, 11, 27),
    ]


@override_settings(TIME_ZONE="UTC", USE_TZ=True)
def test_explicit_dates():
    windows = generate_explicit(
        dates=[date(2026, 9, 15), date(2026, 10, 13), date(2026, 11, 10)],
        start_time=time(18, 0),
        end_time=time(19, 30),
    )
    assert len(windows) == 3
    assert [w.start_at.date() for w in windows] == [
        date(2026, 9, 15),
        date(2026, 10, 13),
        date(2026, 11, 10),
    ]


def test_weekly_rejects_unknown_weekday():
    with pytest.raises(ValueError, match="Unknown weekday"):
        generate_weekly(
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            weekdays=["XX"],
            start_time=time(10, 0),
            end_time=time(12, 0),
        )


def test_weekly_rejects_empty_weekdays():
    with pytest.raises(ValueError, match="At least one weekday"):
        generate_weekly(
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            weekdays=[],
            start_time=time(10, 0),
            end_time=time(12, 0),
        )


def test_rejects_inverted_dates():
    with pytest.raises(ValueError, match="end_date must be"):
        generate_weekly(
            start_date=date(2026, 9, 30),
            end_date=date(2026, 9, 1),
            weekdays=["MO"],
            start_time=time(10, 0),
            end_time=time(12, 0),
        )


def test_rejects_inverted_times():
    with pytest.raises(ValueError, match="end_time must be"):
        generate_weekly(
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            weekdays=["MO"],
            start_time=time(12, 0),
            end_time=time(10, 0),
        )


def test_monthly_rejects_bad_week_position():
    with pytest.raises(ValueError, match="week_positions must be"):
        generate_monthly_ordinal(
            start_date=date(2026, 9, 1),
            end_date=date(2026, 12, 31),
            weekdays=["SA"],
            week_positions=[0],
            start_time=time(10, 0),
            end_time=time(12, 0),
        )
