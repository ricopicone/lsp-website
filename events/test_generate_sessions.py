"""Smoke tests for the ``generate_sessions`` management command."""

from __future__ import annotations

from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from events.models import Event, Session


def _make_event():
    return Event.objects.create(
        title="Test", slug="test",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 31),
    )


@pytest.mark.django_db
def test_weekly_creates_sessions():
    event = _make_event()
    call_command(
        "generate_sessions",
        "test",
        "--weekly",
        "--weekdays", "TH",
        "--start", "2026-09-01",
        "--end", "2026-09-30",
        "--time", "10:00-12:00",
        stdout=StringIO(),
    )
    # Thursdays in Sep 2026: 3, 10, 17, 24
    assert event.sessions.count() == 4


@pytest.mark.django_db
def test_dry_run_creates_nothing(tmp_path):
    event = _make_event()
    out = StringIO()
    call_command(
        "generate_sessions",
        "test",
        "--weekly",
        "--weekdays", "TH",
        "--start", "2026-09-01",
        "--end", "2026-09-30",
        "--time", "10:00-12:00",
        "--dry-run",
        stdout=out,
    )
    assert event.sessions.count() == 0
    assert "Will show 4 session(s)" in out.getvalue()


@pytest.mark.django_db
def test_clear_drops_existing_then_creates():
    event = _make_event()
    Session.objects.create(
        event=event,
        start_at="2025-01-01T10:00:00Z",
        end_at="2025-01-01T11:00:00Z",
        sequence=1,
    )
    call_command(
        "generate_sessions",
        "test",
        "--weekly",
        "--weekdays", "TH",
        "--start", "2026-09-01",
        "--end", "2026-09-30",
        "--time", "10:00-12:00",
        "--clear",
        stdout=StringIO(),
    )
    assert event.sessions.count() == 4  # old one gone


@pytest.mark.django_db
def test_unknown_event_errors():
    with pytest.raises(CommandError, match="No event with slug"):
        call_command(
            "generate_sessions",
            "nope",
            "--weekly",
            "--weekdays", "TH",
            "--start", "2026-09-01",
            "--end", "2026-09-30",
            "--time", "10:00-12:00",
            stdout=StringIO(),
        )


@pytest.mark.django_db
def test_missing_required_option():
    _make_event()
    with pytest.raises(CommandError, match="Missing required"):
        call_command(
            "generate_sessions",
            "test",
            "--weekly",
            "--time", "10:00-12:00",
            stdout=StringIO(),
        )
