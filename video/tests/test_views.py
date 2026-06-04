from __future__ import annotations

import pytest
from django.urls import reverse

from registrations.models import Registration

from .factories import daily_on, register, seminar, user

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _mock_daily(monkeypatch):
    """Every view test gets a stubbed Daily API (no network)."""
    monkeypatch.setattr(
        "video.daily.create_room",
        lambda name, properties=None: {"name": name, "url": f"https://lsp.daily.co/{name}"},
    )
    monkeypatch.setattr(
        "video.daily.create_meeting_token",
        lambda **kw: "tok-abc",
    )


def _room_url(event):
    return reverse("video:event_room", args=[event.slug])


def test_anonymous_is_redirected_to_login():
    event = seminar()
    event.ensure_workgroup()
    resp = pytest.importorskip("django.test").Client().get(_room_url(event))
    assert resp.status_code == 302
    assert "/accounts/login" in resp.url or "/login" in resp.url


@daily_on
def test_non_member_is_forbidden(client):
    event = seminar()
    event.ensure_workgroup()
    outsider = user("out@x.test")
    client.force_login(outsider)
    assert client.get(_room_url(event)).status_code == 403


@daily_on
def test_paid_registrant_gets_room(client):
    event = seminar()
    event.ensure_workgroup()
    member = user("m@x.test")
    register(member, event, status=Registration.Status.PAID)
    client.force_login(member)
    resp = client.get(_room_url(event))
    assert resp.status_code == 200
    assert b"room-token" in resp.content
    assert b"This meeting is not recorded" in resp.content


@daily_on
def test_faculty_joins_as_moderator(client):
    event = seminar()
    teacher = user("teach@x.test", is_faculty=True)
    event.add_faculty(teacher)
    client.force_login(teacher)
    resp = client.get(_room_url(event))
    assert resp.status_code == 200
    assert b"mute or remove" in resp.content  # host moderation hint


def test_disabled_renders_fallback(client):
    # Feature flag off (default) -> graceful "unavailable" page, not a crash.
    event = seminar()
    event.ensure_workgroup()
    member = user("m2@x.test")
    register(member, event, status=Registration.Status.PAID)
    client.force_login(member)
    resp = client.get(_room_url(event))
    assert resp.status_code == 200
    assert b"unavailable" in resp.content.lower()
