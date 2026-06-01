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
    from events.models import Program
    program = Program.objects.create(
        academic_year="2026-2027", name="Program 2026-2027",
        published=True,
    )
    e = Event.objects.create(
        title="Lacan Seminar XI",
        slug="lacan-seminar-xi",
        description="The four fundamental concepts.",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 15),
        status=Event.Status.OPEN,
        published=True,
        program=program,
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
    from events.models import Program
    program = Program.objects.get_or_create(
        academic_year="2026-2027",
        defaults={"name": "Program 2026-2027", "published": False},
    )[0]
    return Event.objects.create(
        title="Draft Event",
        slug="draft-event",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 15),
        status=Event.Status.DRAFT,
        published=False,
        program=program,
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
    published_event.add_faculty(faculty)
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


@pytest.mark.django_db
def test_access_info_visible_to_paid_registrant(client, published_event):
    """When the current user has a paid Registration, the event page shows access info."""
    from registrations.models import Registration

    published_event.access_info = "Zoom: https://example.zoom.us/j/123 — password: SECRETZOOM"
    published_event.save()
    user = User.objects.create_user(email="paid@example.com")
    tier = published_event.price_tiers.first()
    Registration.objects.create(
        user=user, event=published_event, price_tier=tier,
        quoted_amount=Decimal("0.00"),
        status=Registration.Status.PAID,
    )
    client.force_login(user)
    response = client.get(reverse("events:detail", args=["lacan-seminar-xi"]))
    assert b"Your access details" in response.content
    assert b"SECRETZOOM" in response.content


@pytest.mark.django_db
def test_access_info_hidden_from_non_paid_user(client, published_event):
    """A user without a paid Registration must not see access info."""
    from registrations.models import Registration

    published_event.access_info = "Zoom: https://example.zoom.us/j/123 — password: SECRETZOOM"
    published_event.save()
    user = User.objects.create_user(email="unpaid@example.com")
    tier = published_event.price_tiers.first()
    Registration.objects.create(
        user=user, event=published_event, price_tier=tier,
        quoted_amount=Decimal("50.00"),
        status=Registration.Status.AWAITING_PAYMENT,
    )
    client.force_login(user)
    response = client.get(reverse("events:detail", args=["lacan-seminar-xi"]))
    assert b"Your access details" not in response.content
    assert b"SECRETZOOM" not in response.content


@pytest.mark.django_db
def test_access_info_hidden_from_anonymous(client, published_event):
    published_event.access_info = "SECRETZOOM"
    published_event.save()
    response = client.get(reverse("events:detail", args=["lacan-seminar-xi"]))
    assert b"SECRETZOOM" not in response.content


# ---- Speakers + Faculty bios + single-session collapse ----------------


@pytest.fixture
def special_event(db):
    from events.models import Audience, PriceTier, Session
    e = Event.objects.create(
        title="Working with Masochism", slug="working-with-masochism",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 6), end_date=date(2026, 9, 6),
        format=Event.Format.ONLINE,
        published=True, status=Event.Status.OPEN,
    )
    Session.objects.create(
        event=e, sequence=1, title="Lecture",
        start_at=datetime(2026, 9, 6, 16, 30, tzinfo=dt_timezone.utc),
        end_at=datetime(2026, 9, 6, 19, 30, tzinfo=dt_timezone.utc),
        location="Online (Zoom)",
    )
    PriceTier.objects.create(
        event=e, audience=Audience.ALL, base_amount=Decimal("100.00")
    )
    return e


def test_special_event_collapses_session_into_event_details(client, special_event):
    response = client.get(reverse("events:detail", args=[special_event.slug]))
    assert b"Event details" in response.content
    assert b"Sessions" not in response.content


def test_seminar_keeps_sessions_table(client, published_event):
    """The existing published_event fixture is a seminar with a session."""
    response = client.get(reverse("events:detail", args=["lacan-seminar-xi"]))
    assert b"Sessions" in response.content


def test_speaker_section_renders_speaker_bios_on_special_event(
    client, special_event,
):
    """For a special_event, the people heading is 'Speakers' and bios render."""
    from events.models import Speaker
    s = Speaker.objects.create(
        name="Stephanie Swales", slug="stephanie-swales",
        bio="Long bio about Swales' clinical work.",
        affiliation="Dublin City University",
    )
    special_event.speakers.add(s)
    response = client.get(reverse("events:detail", args=[special_event.slug]))
    assert b"Speakers" in response.content
    assert b"Stephanie Swales" in response.content
    assert b"Dublin City University" in response.content
    assert b"Long bio about Swales" in response.content


@pytest.mark.django_db
def test_faculty_section_label_for_seminar(client, published_event):
    """Seminars use 'Faculty' wording when faculty are attached."""
    user = User.objects.create_user(email="seminar-fac@example.com",
                                    first_name="Jane", last_name="Doe")
    user.profile.is_faculty = True
    user.profile.bio = "Jane has a teaching bio."
    user.profile.save()
    published_event.add_faculty(user)
    response = client.get(reverse("events:detail", args=["lacan-seminar-xi"]))
    body = response.content
    assert b"Faculty" in body
    assert b"teaching bio" in body


def test_speaker_section_hides_non_public_speakers(client, special_event):
    from events.models import Speaker
    Speaker.objects.create(
        name="Hidden Speaker", slug="hidden",
        bio="Should not appear.",
        public=False,
    )
    s_visible = Speaker.objects.create(
        name="Visible Speaker", slug="visible",
        bio="Visible to all.",
        public=True,
    )
    special_event.speakers.add(s_visible)
    # Add hidden speaker to event too
    hidden = Speaker.objects.get(slug="hidden")
    special_event.speakers.add(hidden)
    response = client.get(reverse("events:detail", args=[special_event.slug]))
    assert b"Visible Speaker" in response.content
    assert b"Hidden Speaker" not in response.content
    assert b"Should not appear" not in response.content


@pytest.mark.django_db
def test_guest_label_replaces_external_in_pricing(client):
    """Audience.EXTERNAL renders as 'Guest' on the public event page."""
    from events.models import Audience, PriceTier
    e = Event.objects.create(
        title="Guest test", slug="guest-test",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 6), end_date=date(2026, 9, 6),
        published=True, status=Event.Status.OPEN,
    )
    PriceTier.objects.create(
        event=e, audience=Audience.EXTERNAL, base_amount=Decimal("50.00")
    )
    response = client.get(reverse("events:detail", args=[e.slug]))
    assert b"Guest" in response.content
    # The old wording should be gone.
    assert b"External / non-LSP" not in response.content
