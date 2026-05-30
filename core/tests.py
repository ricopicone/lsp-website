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
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 15),
        published=True,
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


@pytest.fixture
def draft_event_with_sessions(db):
    e = Event.objects.create(
        title="Draft Event",
        slug="draft-event",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 15),
        published=False,
    )
    Session.objects.create(
        event=e, start_at=_utc(2026, 9, 5), end_at=_utc(2026, 9, 5, 12), sequence=1
    )
    return e


@pytest.mark.django_db
def test_calendar_page_public_no_auth(client):
    """Calendar is publicly viewable post-M5; no login required."""
    response = client.get(reverse("core:calendar"))
    assert response.status_code == 200
    assert b"FullCalendar" in response.content


def test_calendar_events_json_anonymous_sees_only_published(
    client, event_with_sessions, draft_event_with_sessions,
):
    response = client.get(reverse("core:calendar_events"))
    assert response.status_code == 200
    titles = {item["title"] for item in response.json()}
    assert "Lacan Seminar XI" in titles
    assert "Draft Event" not in titles


def test_calendar_events_json_staff_sees_drafts(
    client, staff_user, event_with_sessions, draft_event_with_sessions,
):
    client.force_login(staff_user)
    response = client.get(reverse("core:calendar_events"))
    titles = {item["title"] for item in response.json()}
    assert "Lacan Seminar XI" in titles
    assert "Draft Event" in titles


def test_calendar_events_json_url_public_for_staff(client, staff_user, event_with_sessions):
    """Calendar event links go to the public event page for everyone —
    including staff. Staff can edit from the event page directly."""
    client.force_login(staff_user)
    response = client.get(reverse("core:calendar_events"))
    first = response.json()[0]
    assert first["url"] == reverse("events:detail", args=["lacan-seminar-xi"])


def test_calendar_events_json_url_public_for_anonymous(client, event_with_sessions):
    response = client.get(reverse("core:calendar_events"))
    first = response.json()[0]
    assert first["url"] == reverse("events:detail", args=["lacan-seminar-xi"])


def test_events_json_filters_by_range(client, event_with_sessions):
    response = client.get(
        reverse("core:calendar_events"),
        {"start": "2026-09-05T00:00:00Z", "end": "2026-09-15T00:00:00Z"},
    )
    data = response.json()
    assert len(data) == 1
    assert data[0]["start"].startswith("2026-09-10")


def test_events_json_accepts_bare_dates(client, event_with_sessions):
    response = client.get(
        reverse("core:calendar_events"),
        {"start": "2026-09-05", "end": "2026-09-15"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1


# ---- Landing page ------------------------------------------------------


@pytest.mark.django_db
def test_landing_page_renders(client):
    response = client.get(reverse("core:landing"))
    assert response.status_code == 200
    assert b"Lacanian School" in response.content
    assert b"lacanschool.org" in response.content  # link to apex


def test_landing_page_lists_upcoming_events(client, event_with_sessions):
    response = client.get(reverse("core:landing"))
    assert b"Lacan Seminar XI" in response.content


def test_landing_page_skips_draft_events(client, draft_event_with_sessions):
    response = client.get(reverse("core:landing"))
    assert b"Draft Event" not in response.content


def test_landing_page_logged_in_shows_recent_registration_link(
    client, regular_user, event_with_sessions,
):
    from decimal import Decimal

    from events.models import Audience, PriceTier
    from registrations.models import Registration
    tier = PriceTier.objects.create(
        event=event_with_sessions, audience=Audience.ALL,
        base_amount=Decimal("100.00"),
    )
    Registration.objects.create(
        user=regular_user, event=event_with_sessions, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.AWAITING_PAYMENT,
    )
    client.force_login(regular_user)
    response = client.get(reverse("core:landing"))
    assert b"View your most recent registration" in response.content


# ---- Public events list -----------------------------------------------


@pytest.mark.django_db
def test_events_list_public(client):
    response = client.get(reverse("events:list"))
    assert response.status_code == 200


def test_events_list_shows_published_upcoming(
    client, event_with_sessions, draft_event_with_sessions,
):
    response = client.get(reverse("events:list"))
    assert b"Lacan Seminar XI" in response.content
    assert b"Draft Event" not in response.content


@pytest.mark.django_db
def test_events_list_excludes_past_events(client):
    """Events that ended before today shouldn't appear in the list."""
    Event.objects.create(
        title="Old Event", slug="old",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2020, 1, 1), end_date=date(2020, 12, 31),
        published=True,
    )
    response = client.get(reverse("events:list"))
    assert b"Old Event" not in response.content


@pytest.mark.django_db
def test_events_list_excludes_annual_program_types(client):
    """Seminars, reading groups, cartels live on /program/, not /events/."""
    future = date(2030, 9, 1)
    for slug, etype in [
        ("a-seminar", Event.Type.SEMINAR),
        ("a-rg", Event.Type.READING_GROUP),
        ("a-cartel", Event.Type.CARTEL),
        ("a-special", Event.Type.SPECIAL_EVENT),
    ]:
        Event.objects.create(
            title=f"Event {slug}", slug=slug, event_type=etype,
            start_date=future, end_date=future, published=True,
        )
    response = client.get(reverse("events:list"))
    assert b"Event a-special" in response.content
    assert b"Event a-seminar" not in response.content
    assert b"Event a-rg" not in response.content
    assert b"Event a-cartel" not in response.content


@pytest.mark.django_db
def test_events_list_hides_members_only_from_anonymous(client, django_user_model):
    """visibility=members_only events are hidden from anonymous visitors."""
    future = date(2030, 9, 1)
    Event.objects.create(
        title="Members Only Talk", slug="members-only-talk",
        event_type=Event.Type.SCHOLARLY_SEMINAR,
        visibility=Event.Visibility.MEMBERS_ONLY,
        start_date=future, end_date=future, published=True,
    )
    Event.objects.create(
        title="Public Talk", slug="public-talk",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=future, end_date=future, published=True,
    )

    # Anonymous: members-only hidden.
    response = client.get(reverse("events:list"))
    assert b"Public Talk" in response.content
    assert b"Members Only Talk" not in response.content

    # Authenticated: visible.
    user = django_user_model.objects.create_user(email="m@example.com", password="x")
    client.force_login(user)
    response = client.get(reverse("events:list"))
    assert b"Members Only Talk" in response.content


@pytest.mark.django_db
def test_event_detail_back_link_seminar_goes_to_program(client):
    """A seminar's back link points to /program/ for its academic year."""
    e = Event.objects.create(
        title="A Seminar", slug="a-seminar-test",
        event_type=Event.Type.SEMINAR,
        start_date=date(2027, 9, 1), end_date=date(2028, 5, 1),
        published=True,
    )
    response = client.get(reverse("events:detail", args=[e.slug]))
    assert response.status_code == 200
    assert b"\xe2\x86\x90 Program" in response.content
    assert b"/program/?year=2027-2028" in response.content


@pytest.mark.django_db
def test_event_detail_back_link_special_goes_to_events(client):
    """A special event's back link points to /events/."""
    e = Event.objects.create(
        title="A Workshop", slug="a-workshop-test",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2027, 10, 1), end_date=date(2027, 10, 1),
        published=True,
    )
    response = client.get(reverse("events:detail", args=[e.slug]))
    assert response.status_code == 200
    assert b"\xe2\x86\x90 Events" in response.content
