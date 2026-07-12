"""Tests for the in-app standalone-event schedule (session) editor."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from committees.models import Committee
from events.models import Event, Session

PACIFIC = ZoneInfo("America/Los_Angeles")


@pytest.fixture
def pc_member(db):
    u = User.objects.create_user(email="pc@x.test", password="x")
    committee, _ = Committee.objects.get_or_create(
        slug="programming-committee", defaults={"name": "Programming Committee"},
    )
    committee.add_member(u, start_date=date(2026, 1, 1))
    return u


def _special_event(slug="talk", with_session=True):
    e = Event.objects.create(
        title="Talk", slug=slug, event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2030, 11, 5), end_date=date(2030, 11, 5), published=True,
    )
    s = None
    if with_session:
        s = Session.objects.create(
            event=e,
            start_at=timezone.make_aware(datetime(2030, 11, 5, 18, 0), PACIFIC),
            end_at=timezone.make_aware(datetime(2030, 11, 5, 20, 0), PACIFIC),
            sequence=1,
        )
    return e, s


def _mgmt(total, initial):
    return {
        "sessions-TOTAL_FORMS": str(total),
        "sessions-INITIAL_FORMS": str(initial),
        "sessions-MIN_NUM_FORMS": "0",
        "sessions-MAX_NUM_FORMS": "1000",
    }


@pytest.mark.django_db
def test_editor_shows_for_special_event_not_seminar(client, pc_member):
    special, _ = _special_event()
    seminar = Event.objects.create(
        title="Sem", slug="sem", event_type=Event.Type.SEMINAR,
        start_date=date(2030, 9, 1), end_date=date(2031, 5, 1),
    )
    client.force_login(pc_member)
    special_html = client.get(reverse("events:edit", args=[special.slug])).content
    seminar_html = client.get(reverse("events:edit", args=[seminar.slug])).content
    assert b"Save schedule" in special_html
    assert b"Save schedule" not in seminar_html


@pytest.mark.django_db
def test_edit_session_datetime_updates_session_and_event(client, pc_member):
    e, s = _special_event()
    client.force_login(pc_member)
    resp = client.post(
        reverse("events:edit_schedule", args=[e.slug]),
        {
            **_mgmt(1, 1),
            "sessions-0-id": str(s.pk),
            "sessions-0-session_date": "2030-11-12",
            "sessions-0-start_time": "19:00",
            "sessions-0-end_time": "21:00",
            "sessions-0-location": "Zoom",
        },
    )
    assert resp.status_code == 302
    s.refresh_from_db()
    assert timezone.localtime(s.start_at, PACIFIC).strftime("%Y-%m-%d %H:%M") == "2030-11-12 19:00"
    assert s.location == "Zoom"
    e.refresh_from_db()
    assert e.start_date == date(2030, 11, 12)


@pytest.mark.django_db
def test_add_session(client, pc_member):
    e, s = _special_event()
    client.force_login(pc_member)
    resp = client.post(
        reverse("events:edit_schedule", args=[e.slug]),
        {
            **_mgmt(2, 1),
            "sessions-0-id": str(s.pk),
            "sessions-0-session_date": "2030-11-05",
            "sessions-0-start_time": "18:00",
            "sessions-0-end_time": "20:00",
            "sessions-0-location": "",
            "sessions-1-id": "",
            "sessions-1-session_date": "2030-11-19",
            "sessions-1-start_time": "18:00",
            "sessions-1-end_time": "20:00",
            "sessions-1-location": "",
        },
    )
    assert resp.status_code == 302
    e.refresh_from_db()
    assert e.sessions.count() == 2
    assert e.end_date == date(2030, 11, 19)


@pytest.mark.django_db
def test_remove_session(client, pc_member):
    e, s = _special_event()
    s2 = Session.objects.create(
        event=e,
        start_at=timezone.make_aware(datetime(2030, 11, 12, 18, 0), PACIFIC),
        end_at=timezone.make_aware(datetime(2030, 11, 12, 20, 0), PACIFIC),
        sequence=2,
    )
    client.force_login(pc_member)
    resp = client.post(
        reverse("events:edit_schedule", args=[e.slug]),
        {
            **_mgmt(2, 2),
            "sessions-0-id": str(s.pk),
            "sessions-0-session_date": "2030-11-05",
            "sessions-0-start_time": "18:00",
            "sessions-0-end_time": "20:00",
            "sessions-0-location": "",
            "sessions-1-id": str(s2.pk),
            "sessions-1-session_date": "2030-11-12",
            "sessions-1-start_time": "18:00",
            "sessions-1-end_time": "20:00",
            "sessions-1-location": "",
            "sessions-1-DELETE": "on",
        },
    )
    assert resp.status_code == 302
    e.refresh_from_db()
    assert e.sessions.count() == 1
    assert not Session.objects.filter(pk=s2.pk).exists()


@pytest.mark.django_db
def test_set_date_on_tbd_event_creates_first_session(client, pc_member):
    e, _ = _special_event(with_session=False)
    assert e.sessions.count() == 0
    client.force_login(pc_member)
    resp = client.post(
        reverse("events:edit_schedule", args=[e.slug]),
        {
            **_mgmt(1, 0),
            "sessions-0-id": "",
            "sessions-0-session_date": "2030-12-01",
            "sessions-0-start_time": "18:00",
            "sessions-0-end_time": "20:00",
            "sessions-0-location": "",
        },
    )
    assert resp.status_code == 302
    e.refresh_from_db()
    assert e.sessions.count() == 1
    assert e.start_date == date(2030, 12, 1)


@pytest.mark.django_db
def test_end_before_start_is_rejected(client, pc_member):
    e, s = _special_event()
    client.force_login(pc_member)
    resp = client.post(
        reverse("events:edit_schedule", args=[e.slug]),
        {
            **_mgmt(1, 1),
            "sessions-0-id": str(s.pk),
            "sessions-0-session_date": "2030-11-05",
            "sessions-0-start_time": "20:00",
            "sessions-0-end_time": "18:00",
            "sessions-0-location": "",
        },
    )
    assert resp.status_code == 200  # re-render with errors
    s.refresh_from_db()
    # unchanged (still 18:00–20:00)
    assert timezone.localtime(s.start_at, PACIFIC).hour == 18


@pytest.mark.django_db
def test_non_editor_forbidden(client):
    e, s = _special_event()
    u = User.objects.create_user(email="nobody@x.test", password="x")
    client.force_login(u)
    resp = client.post(
        reverse("events:edit_schedule", args=[e.slug]),
        {**_mgmt(0, 0)},
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_non_standalone_type_404(client, pc_member):
    seminar = Event.objects.create(
        title="Sem", slug="sem", event_type=Event.Type.SEMINAR,
        start_date=date(2030, 9, 1), end_date=date(2031, 5, 1),
    )
    client.force_login(pc_member)
    resp = client.post(
        reverse("events:edit_schedule", args=[seminar.slug]),
        {**_mgmt(0, 0)},
    )
    assert resp.status_code == 404
