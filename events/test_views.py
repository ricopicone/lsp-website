"""Tests for the public-facing event views (PROG-1)."""

from __future__ import annotations

from datetime import date, datetime
from datetime import timezone as dt_timezone
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import User
from events.models import Event, PriceTier, Session


def _utc(year, month, day, hour=10, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=dt_timezone.utc)


@pytest.fixture
def published_event(db):
    e = Event.objects.create(
        title="Lacan Seminar XI",
        slug="lacan-seminar-xi",
        description="The four fundamental concepts.",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 15),
        status=Event.Status.OPEN,
        published=True,
    )
    Session.objects.create(
        event=e, start_at=_utc(2026, 9, 3), end_at=_utc(2026, 9, 3, 12),
        sequence=1, location="Online",
    )
    PriceTier.objects.create(
        event=e, base_amount=Decimal("100.00"), audience="all",
    )
    PriceTier.objects.create(
        event=e, base_amount=Decimal("60.00"),
        audience="student", sliding_scale=True,
        minimum_amount=Decimal("0.00"),
    )
    return e


@pytest.fixture
def draft_event(db):
    return Event.objects.create(
        title="Draft Event",
        slug="draft-event",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 15),
        status=Event.Status.DRAFT,
        published=False,
    )


def test_published_event_renders_for_anonymous(client, published_event):
    response = client.get(reverse("events:detail", args=["lacan-seminar-xi"]))
    assert response.status_code == 200
    assert b"Lacan Seminar XI" in response.content
    assert b"The four fundamental concepts" in response.content
    # Sessions + pricing in the body
    assert b"Online" in response.content
    assert b"100.00" in response.content
    assert b"sliding from" in response.content


def test_published_event_shows_faculty_names(client, published_event):
    faculty = User.objects.create_user(
        email="fac@example.com", first_name="Jane", last_name="Doe",
    )
    faculty.profile.is_faculty = True
    faculty.profile.save()
    published_event.faculty.add(faculty)
    response = client.get(reverse("events:detail", args=["lacan-seminar-xi"]))
    assert b"Jane Doe" in response.content


def test_draft_event_404s_for_anonymous(client, draft_event):
    response = client.get(reverse("events:detail", args=["draft-event"]))
    assert response.status_code == 404


def test_draft_event_visible_to_staff_with_preview_badge(client, draft_event):
    staff = User.objects.create_user(email="staff@example.com")
    staff.is_staff = True
    staff.save()
    client.force_login(staff)
    response = client.get(reverse("events:detail", args=["draft-event"]))
    assert response.status_code == 200
    assert b"Draft preview" in response.content


@pytest.mark.django_db
def test_nonexistent_slug_404s(client):
    response = client.get(reverse("events:detail", args=["does-not-exist"]))
    assert response.status_code == 404
