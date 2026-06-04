"""Workgroup Meet tab + 'meeting in progress' indicator."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, User
from events.models import Event
from workgroups.models import WorkgroupMembership

pytestmark = pytest.mark.django_db

daily_on = override_settings(
    DAILY_ENABLED=True, DAILY_API_KEY="k", DAILY_DOMAIN="lsp.daily.co"
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
def test_overview_shows_in_progress_banner(client):
    user = _member()
    wg = _wg_with_member(user)
    now = timezone.now()
    _meeting(wg, start=now - timedelta(minutes=5), end=now + timedelta(minutes=55))
    client.force_login(user)
    resp = client.get(reverse("workgroups:detail", args=[wg.slug]))
    assert resp.status_code == 200
    assert b"Join Meeting in Progress" in resp.content


def test_meet_tab_hidden_when_video_disabled(client):
    # Default settings: DAILY off -> no Meet tab.
    user = _member()
    wg = _wg_with_member(user)
    client.force_login(user)
    resp = client.get(reverse("workgroups:detail", args=[wg.slug]) + "?tab=meet")
    # Unknown/!available tab falls back to overview; no "Meet Now" anywhere.
    assert b"Meet Now" not in resp.content
