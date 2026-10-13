"""Workgroup Meet tab + 'meeting in progress' indicator."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, User
from events.models import Event
from video.models import DailyRoom
from workgroups.models import WorkgroupMembership

pytestmark = pytest.mark.django_db

daily_on = override_settings(
    DAILY_ENABLED=True, DAILY_API_KEY="k", DAILY_DOMAIN="lsp.daily.co"
)


@pytest.fixture(autouse=True)
def _clear_presence_cache():
    cache.clear()
    yield
    cache.clear()


def _provision_room(wg):
    return DailyRoom.objects.create(
        workgroup=wg, name=f"lsp-{wg.slug}",
        url=f"https://lsp.daily.co/lsp-{wg.slug}", provider_created=True,
    )


def _member(email="m@x.test"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    return u


def _wg_with_member(user):
    wg = Event.objects.create(
        title="Cartel A", slug="cartel-a", event_type=Event.Type.CARTEL,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
    ).ensure_workgroup()
    WorkgroupMembership.objects.create(
        workgroup=wg, user=user, role=WorkgroupMembership.Role.MEMBER,
        start_date=date(2026, 1, 1),
    )
    return wg


def _meeting(wg, *, start, end, cancelled=False, title="Weekly"):
    return wg.meetings.create(
        title=title, starts_at=start, ends_at=end, cancelled=cancelled
    )


def test_ongoing_meeting_only_within_window():
    wg = _wg_with_member(_member())
    now = timezone.now()
    assert wg.ongoing_meeting() is None
    _meeting(wg, start=now - timedelta(minutes=10), end=now + timedelta(minutes=50))
    assert wg.ongoing_meeting() is not None
    # A cancelled meeting in-window doesn't count.
    wg.meetings.update(cancelled=True)
    assert wg.ongoing_meeting() is None


def test_past_meeting_is_not_ongoing():
    wg = _wg_with_member(_member())
    now = timezone.now()
    _meeting(wg, start=now - timedelta(hours=3), end=now - timedelta(hours=2))
    assert wg.ongoing_meeting() is None


@daily_on
def test_meet_tab_visible_to_member(client):
    user = _member()
    wg = _wg_with_member(user)
    client.force_login(user)
    resp = client.get(reverse("workgroups:detail", args=[wg.slug]) + "?tab=meet")
    assert resp.status_code == 200
    assert b"Meet Now" in resp.content


@daily_on
def test_overview_shows_in_progress_banner_when_room_is_live(client, monkeypatch):
    user = _member()
    wg = _wg_with_member(user)
    room = _provision_room(wg)
    monkeypatch.setattr(
        "video.daily.get_presence", lambda: {room.name: [{"userName": "A"}, {"userName": "B"}]}
    )
    client.force_login(user)
    resp = client.get(reverse("workgroups:detail", args=[wg.slug]))
    assert resp.status_code == 200
    assert b"Join Meeting in Progress" in resp.content
    assert b"2 in the room" in resp.content


@daily_on
def test_overview_has_no_banner_when_room_empty(client, monkeypatch):
    user = _member()
    wg = _wg_with_member(user)
    _provision_room(wg)
    monkeypatch.setattr("video.daily.get_presence", lambda: {})
    client.force_login(user)
    resp = client.get(reverse("workgroups:detail", args=[wg.slug]))
    assert resp.status_code == 200
    assert b"Join Meeting in Progress" not in resp.content


def test_meet_tab_hidden_when_video_disabled(client):
    # Default settings: DAILY off -> no Meet tab.
    user = _member()
    wg = _wg_with_member(user)
    client.force_login(user)
    resp = client.get(reverse("workgroups:detail", args=[wg.slug]) + "?tab=meet")
    # Unknown/!available tab falls back to overview; no "Meet Now" anywhere.
    assert b"Meet Now" not in resp.content


# ---- An offering that meets elsewhere (task #817) ---------------------------


def _zoom_seminar():
    event = Event.objects.create(
        title="Clinical Practice", slug="clinical-practice",
        event_type=Event.Type.SEMINAR, format=Event.Format.ONLINE,
        online_venue=Event.OnlineVenue.EXTERNAL,
        access_info="https://zoom.example/j/123",
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
        published=True,
    )
    return event, event.ensure_workgroup()


def _meet(client, wg):
    return client.get(reverse("workgroups:detail", args=[wg.slug]) + "?tab=meet")


@daily_on
def test_meet_tab_shows_an_external_venue_and_its_link_to_faculty(client):
    event, wg = _zoom_seminar()
    fac = _member("fac@x.test")
    event.add_faculty(fac)
    client.force_login(fac)
    body = _meet(client, wg).content.decode()
    assert "meets outside the site" in body
    assert "https://zoom.example/j/123" in body
    # The group's own room stays, for meeting outside class.
    assert "Meet Now" in body


@daily_on
def test_meet_tab_withholds_the_link_from_a_member_without_access(client):
    """A stored member who hasn't paid is told where class meets, not the link:
    the same rule as the event page's access details."""
    _event, wg = _zoom_seminar()
    user = _member()
    WorkgroupMembership.objects.create(
        workgroup=wg, user=user, role=WorkgroupMembership.Role.MEMBER,
        start_date=date(2026, 1, 1),
    )
    client.force_login(user)
    body = _meet(client, wg).content.decode()
    assert "meets outside the site" in body
    assert "https://zoom.example/j/123" not in body


@daily_on
def test_meet_tab_says_nothing_extra_for_an_insite_offering(client):
    event, wg = _zoom_seminar()
    Event.objects.filter(pk=event.pk).update(online_venue=Event.OnlineVenue.INSITE)
    fac = _member("fac@x.test")
    event.add_faculty(fac)
    client.force_login(fac)
    body = _meet(client, wg).content.decode()
    assert "meets outside the site" not in body
