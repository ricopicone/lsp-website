"""Tests for the Program model + cascading visibility (PROG-2 redesign)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from committees.models import Committee, CommitteeMembership
from events.models import Event, Program


@pytest.mark.django_db
def test_is_public_now_true_when_published():
    p = Program.objects.create(academic_year="2030-2031", published=True)
    assert p.is_public_now is True


@pytest.mark.django_db
def test_is_public_now_true_when_publish_date_in_past():
    p = Program.objects.create(
        academic_year="2030-2031",
        publish_date=timezone.now() - timedelta(days=1),
    )
    assert p.is_public_now is True


@pytest.mark.django_db
def test_is_public_now_false_when_publish_date_in_future():
    p = Program.objects.create(
        academic_year="2030-2031",
        publish_date=timezone.now() + timedelta(days=30),
    )
    assert p.is_public_now is False


@pytest.mark.django_db
def test_is_public_now_false_when_neither_set():
    p = Program.objects.create(academic_year="2030-2031")
    assert p.is_public_now is False


@pytest.mark.django_db
def test_event_is_public_now_cascades_from_program():
    program = Program.objects.create(academic_year="2030-2031", published=False)
    e = Event.objects.create(
        title="Hidden Seminar", slug="hidden-seminar",
        event_type=Event.Type.SEMINAR,
        start_date=date(2030, 9, 1), end_date=date(2031, 5, 1),
        published=True,  # ignored for program-type events when program is attached
        program=program,
    )
    assert e.is_public_now is False
    program.published = True
    program.save()
    e.refresh_from_db()
    assert e.is_public_now is True


@pytest.mark.django_db
def test_program_view_404s_unpublished_program_for_anonymous(client):
    Program.objects.create(academic_year="2030-2031", published=False)
    resp = client.get(reverse("program") + "?year=2030-2031")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_program_view_shows_unpublished_to_staff(client):
    Program.objects.create(academic_year="2030-2031", published=False)
    u = User.objects.create_user(email="staff@x.test", password="x")
    u.is_staff = True
    u.save()
    client.force_login(u)
    resp = client.get(reverse("program") + "?year=2030-2031")
    assert resp.status_code == 200
    assert b"2030-2031" in resp.content


@pytest.mark.django_db
def test_program_view_shows_unpublished_to_pc_member(client):
    Program.objects.create(academic_year="2030-2031", published=False)
    u = User.objects.create_user(email="pc@x.test", password="x")
    committee, _ = Committee.objects.get_or_create(
        slug="programming-committee",
        defaults={"name": "Programming Committee"},
    )
    CommitteeMembership.objects.create(
        user=u, committee=committee,
        start_date=date(2026, 1, 1),
    )
    client.force_login(u)
    resp = client.get(reverse("program") + "?year=2030-2031")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_event_detail_404s_when_program_unpublished_for_anonymous(client):
    program = Program.objects.create(academic_year="2030-2031", published=False)
    Event.objects.create(
        title="Hidden", slug="hidden-event",
        event_type=Event.Type.SEMINAR,
        start_date=date(2030, 9, 1), end_date=date(2031, 5, 1),
        program=program,
    )
    resp = client.get(reverse("events:detail", args=["hidden-event"]))
    assert resp.status_code == 404
