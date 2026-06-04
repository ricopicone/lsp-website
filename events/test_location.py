"""Context-aware event location display + live-window timing."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, User
from events.models import Audience, Event, PriceTier, Session
from registrations.models import Registration

pytestmark = pytest.mark.django_db

daily_on = override_settings(DAILY_ENABLED=True, DAILY_API_KEY="k", DAILY_DOMAIN="lsp.daily.co")


def _event(slug="talk", fmt=Event.Format.ONLINE):
    return Event.objects.create(
        title="Special Talk", slug=slug, event_type=Event.Type.SPECIAL_EVENT,
        format=fmt, start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
        published=True, status=Event.Status.OPEN,
    )


def _session(event, *, start, end, location="Online (Zoom)"):
    return Session.objects.create(
        event=event, start_at=start, end_at=end, location=location, sequence=1
    )


def _member(email="m@x.test"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    return u


def _register(u, e, status=Registration.Status.PAID):
    tier = e.price_tiers.first() or PriceTier.objects.create(
        event=e, audience=Audience.ALL, base_amount=Decimal("0.00")
    )
    return Registration.objects.create(
        user=u, event=e, price_tier=tier, quoted_amount=Decimal("0.00"), status=status
    )


def test_live_session_window():
    e = _event()
    now = timezone.now()
    # In window (started 5 min ago).
    s = _session(e, start=now - timedelta(minutes=5), end=now + timedelta(minutes=55))
    assert e.live_session() == s and e.is_live() is True
    # Far future: not live, but is the next session.
    s.start_at = now + timedelta(hours=3)
    s.end_at = now + timedelta(hours=4)
    s.save()
    assert e.live_session() is None and e.is_live() is False
    assert e.next_session() == s


def test_preopen_buffer_makes_it_live_early():
    e = _event()
    now = timezone.now()
    # Starts in 10 min — within the 15-min pre-open buffer → live.
    _session(e, start=now + timedelta(minutes=10), end=now + timedelta(minutes=70))
    assert e.is_live() is True


def test_anon_sees_label_and_register_not_zoom(client):
    e = _event()
    now = timezone.now()
    _session(e, start=now + timedelta(days=2), end=now + timedelta(days=2, hours=1))
    resp = client.get(reverse("events:detail", args=[e.slug]))
    assert resp.status_code == 200
    assert b"Online \xc2\xb7 video meeting" in resp.content  # "Online · video meeting"
    assert b"Register for details" in resp.content
    assert b"Zoom" not in resp.content


@daily_on
def test_registered_before_live_sees_appears_message(client):
    e = _event()
    now = timezone.now()
    _session(e, start=now + timedelta(days=1), end=now + timedelta(days=1, hours=1))
    u = _member()
    _register(u, e)
    client.force_login(u)
    resp = client.get(reverse("events:detail", args=[e.slug]))
    assert b"appears here when the event begins" in resp.content
    assert b"Test your video" in resp.content
    assert b"Join the meeting room" not in resp.content


@daily_on
def test_registered_when_live_sees_join(client):
    e = _event()
    now = timezone.now()
    _session(e, start=now - timedelta(minutes=5), end=now + timedelta(minutes=55))
    u = _member()
    _register(u, e)
    client.force_login(u)
    resp = client.get(reverse("events:detail", args=[e.slug]))
    assert b"Join the meeting room" in resp.content


def test_in_person_shows_venue_not_online(client):
    e = _event(slug="inperson", fmt=Event.Format.IN_PERSON)
    now = timezone.now()
    _session(e, start=now + timedelta(days=1), end=now + timedelta(days=1, hours=1),
             location="Room 12, 123 Main St")
    resp = client.get(reverse("events:detail", args=[e.slug]))
    assert b"Room 12, 123 Main St" in resp.content
    assert b"video meeting" not in resp.content
