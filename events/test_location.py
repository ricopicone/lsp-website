"""Context-aware event location display + live-window timing."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, User
from events.models import Audience, Event, PriceTier, Session
from registrations.models import Registration
from video.models import DailyRoom

pytestmark = pytest.mark.django_db

daily_on = override_settings(DAILY_ENABLED=True, DAILY_API_KEY="k", DAILY_DOMAIN="lsp.daily.co")


@pytest.fixture(autouse=True)
def _clear_presence_cache():
    cache.clear()
    yield
    cache.clear()


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


@daily_on
def test_registered_sees_live_now_when_room_occupied(client, monkeypatch):
    # A special event stays on the detail page and owns its own room (it no longer
    # shares the Programming Committee's). Occupy that room so only real presence
    # (not the schedule) makes it "live".
    e = _event(slug="live-talk")
    now = timezone.now()
    _session(e, start=now + timedelta(days=3), end=now + timedelta(days=3, hours=1))
    room = DailyRoom.objects.create(
        event=e, name=f"lsp-event-{e.slug}",
        url=f"https://lsp.daily.co/lsp-event-{e.slug}", provider_created=True,
    )
    monkeypatch.setattr("video.daily.get_presence", lambda: {room.name: [{"u": 1}, {"u": 2}]})
    u = _member()
    _register(u, e)
    client.force_login(u)
    resp = client.get(reverse("events:detail", args=[e.slug]))
    assert b"Live now \xc2\xb7 2 in the room" in resp.content  # "Live now · 2 in the room"
    assert b"Join the meeting room" in resp.content


def test_not_yet_open_shows_no_register_link(client):
    # Published but registration not yet open, seen by a regular (non-host)
    # member. The "Register for details" link would 404, so it must not show —
    # they get the opening-soon wording instead. (A host would see the room
    # affordance, not this gate — covered by the presenter tests above.)
    e = _event(slug="draft-talk")
    e.status = Event.Status.DRAFT
    e.save()
    now = timezone.now()
    _session(e, start=now + timedelta(days=2), end=now + timedelta(days=2, hours=1))
    u = _member()
    client.force_login(u)
    resp = client.get(reverse("events:detail", args=[e.slug]))
    assert resp.status_code == 200
    assert b"Register for details" not in resp.content
    assert b"once registration opens" in resp.content


def test_closed_shows_no_register_link(client):
    # Closed registration: no link (it 404s), closed wording instead.
    e = _event(slug="closed-talk")
    e.status = Event.Status.CLOSED
    e.save()
    now = timezone.now()
    _session(e, start=now + timedelta(days=2), end=now + timedelta(days=2, hours=1))
    resp = client.get(reverse("events:detail", args=[e.slug]))
    assert resp.status_code == 200
    assert b"Register for details" not in resp.content
    assert b"Registration is closed" in resp.content


def _presenter(event, email="speaker@x.test"):
    """An LSP member listed as a speaker on the event (grants can_edit_event via
    Event.is_presenter for a non-offering event) — not registered."""
    u = _member(email=email)
    event.member_speakers.add(u)
    return u


@daily_on
def test_presenter_sees_room_without_registering(client):
    # A speaker never registers/pays for their own event; the join affordance
    # must not be behind the registration gate for them.
    e = _event(slug="spk-talk")
    now = timezone.now()
    _session(e, start=now + timedelta(days=2), end=now + timedelta(days=2, hours=1))
    u = _presenter(e)
    client.force_login(u)
    resp = client.get(reverse("events:detail", args=[e.slug]))
    assert b"Register for details" not in resp.content
    assert b"Open room (host)" in resp.content


@daily_on
def test_presenter_sees_join_when_live(client):
    e = _event(slug="spk-live")
    now = timezone.now()
    _session(e, start=now - timedelta(minutes=5), end=now + timedelta(minutes=55))
    u = _presenter(e)
    client.force_login(u)
    resp = client.get(reverse("events:detail", args=[e.slug]))
    assert b"Join the meeting room" in resp.content
    assert b"Register for details" not in resp.content


@daily_on
def test_presenter_sees_clarifying_text_about_how_attendees_join(client):
    e = _event(slug="spk-help")
    now = timezone.now()
    _session(e, start=now + timedelta(days=2), end=now + timedelta(days=2, hours=1))
    u = _presenter(e)
    client.force_login(u)
    resp = client.get(reverse("events:detail", args=[e.slug]))
    # Explains the attendee mechanism so a speaker can answer "how do I join?".
    assert b"no separate meeting link" in resp.content


@daily_on
def test_presenter_sees_room_in_faculty_view(client):
    e = _event(slug="spk-facview")
    now = timezone.now()
    _session(e, start=now + timedelta(days=2), end=now + timedelta(days=2, hours=1))
    u = _presenter(e)
    client.force_login(u)
    resp = client.get(reverse("events:detail", args=[e.slug]) + "?view=faculty")
    assert b"Open room (host)" in resp.content
    assert b"no separate meeting link" in resp.content


@daily_on
def test_anon_still_sees_register_gate_not_room(client):
    # The gate change must not leak the host affordance to logged-out visitors.
    e = _event(slug="anon-gate")
    now = timezone.now()
    _session(e, start=now + timedelta(days=2), end=now + timedelta(days=2, hours=1))
    resp = client.get(reverse("events:detail", args=[e.slug]))
    assert b"Register for details" in resp.content
    assert b"Open room (host)" not in resp.content
    assert b"no separate meeting link" not in resp.content


def test_in_person_shows_venue_not_online(client):
    e = _event(slug="inperson", fmt=Event.Format.IN_PERSON)
    now = timezone.now()
    _session(e, start=now + timedelta(days=1), end=now + timedelta(days=1, hours=1),
             location="Room 12, 123 Main St")
    resp = client.get(reverse("events:detail", args=[e.slug]))
    assert b"Room 12, 123 Main St" in resp.content
    assert b"video meeting" not in resp.content
