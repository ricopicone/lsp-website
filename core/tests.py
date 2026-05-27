"""Tests for the unified calendar (PROG-6)."""

from __future__ import annotations

from datetime import date, datetime
from datetime import timezone as dt_timezone

import pytest
from django.urls import reverse

from accounts.models import User
from events.models import Event, Session


def _utc(year, month, day, hour=10, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=dt_timezone.utc)


@pytest.fixture
def staff_user(db):
    user = User.objects.create_user(
        email="staff@example.com",
        password="not-a-real-password",
    )
    user.is_staff = True
    user.save()
    return user


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(
        email="member@example.com",
        password="not-a-real-password",
    )


@pytest.fixture
def event_with_sessions(db):
    e = Event.objects.create(
        title="Lacan Seminar XI",
        slug="lacan-seminar-xi",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 15),
    )
    Session.objects.create(
        event=e, start_at=_utc(2026, 9, 3), end_at=_utc(2026, 9, 3, 12), sequence=1
    )
    Session.objects.create(
        event=e, start_at=_utc(2026, 9, 10), end_at=_utc(2026, 9, 10, 12), sequence=2
    )
    Session.objects.create(
        event=e, start_at=_utc(2026, 9, 17), end_at=_utc(2026, 9, 17, 12), sequence=3
    )
    return e


def test_calendar_page_redirects_anonymous(client):
    response = client.get(reverse("core:calendar"))
    assert response.status_code == 302
    assert "/admin/login/" in response.url or "/accounts/login/" in response.url


def test_calendar_page_forbids_non_staff(client, regular_user):
    client.force_login(regular_user)
    response = client.get(reverse("core:calendar"))
    assert response.status_code == 302


def test_calendar_page_renders_for_staff(client, staff_user):
    client.force_login(staff_user)
    response = client.get(reverse("core:calendar"))
    assert response.status_code == 200
    assert b"FullCalendar" in response.content
    assert b"LSP Calendar" in response.content


def test_events_json_returns_sessions(client, staff_user, event_with_sessions):
    client.force_login(staff_user)
    response = client.get(reverse("core:calendar_events"))
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    assert {item["title"] for item in data} == {"Lacan Seminar XI"}
    first = data[0]
    assert first["start"].startswith("2026-09-03")
    assert first["url"].endswith(f"/admin/events/event/{event_with_sessions.id}/change/")


def test_events_json_filters_by_range(client, staff_user, event_with_sessions):
    client.force_login(staff_user)
    response = client.get(
        reverse("core:calendar_events"),
        {"start": "2026-09-05T00:00:00Z", "end": "2026-09-15T00:00:00Z"},
    )
    data = response.json()
    assert len(data) == 1
    assert data[0]["start"].startswith("2026-09-10")


def test_events_json_accepts_bare_dates(client, staff_user, event_with_sessions):
    client.force_login(staff_user)
    response = client.get(
        reverse("core:calendar_events"),
        {"start": "2026-09-05", "end": "2026-09-15"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_events_json_forbids_non_staff(client, regular_user):
    client.force_login(regular_user)
    response = client.get(reverse("core:calendar_events"))
    assert response.status_code == 302
