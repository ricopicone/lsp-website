"""Tests for the Program Committee admin interface."""

from __future__ import annotations

from datetime import date

import pytest
from django.urls import reverse

from accounts.models import User
from committees.models import Committee, CommitteeMembership
from events.models import Event, Program


@pytest.fixture
def pc_member(db):
    u = User.objects.create_user(email="pc@x.test", password="x")
    committee, _ = Committee.objects.get_or_create(
        slug="programming-committee",
        defaults={"name": "Programming Committee"},
    )
    CommitteeMembership.objects.create(
        user=u, committee=committee,
        start_date=date(2026, 1, 1),
    )
    return u


@pytest.fixture
def staff_user(db):
    u = User.objects.create_user(email="staff@x.test", password="x")
    u.is_staff = True
    u.save()
    return u


@pytest.fixture
def program(db):
    return Program.objects.create(academic_year="2030-2031", published=False)


# --- Permissions --------------------------------------------------------


@pytest.mark.django_db
def test_pc_admin_404s_for_anonymous(client, program):
    resp = client.get(reverse("program_admin_programs"))
    # Anonymous redirects to login first.
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_pc_admin_404s_for_regular_user(client, program):
    u = User.objects.create_user(email="nobody@x.test", password="x")
    client.force_login(u)
    resp = client.get(reverse("program_admin_programs"))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_pc_admin_open_for_pc_member(client, program, pc_member):
    client.force_login(pc_member)
    resp = client.get(reverse("program_admin_programs"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_pc_admin_open_for_staff(client, program, staff_user):
    client.force_login(staff_user)
    resp = client.get(reverse("program_admin_programs"))
    assert resp.status_code == 200


# --- Index --------------------------------------------------------------


@pytest.mark.django_db
def test_program_admin_index_lists_all_programs(client, pc_member):
    Program.objects.create(academic_year="2025-2026", published=True)
    Program.objects.create(academic_year="2026-2027", published=False)
    client.force_login(pc_member)
    resp = client.get(reverse("program_admin_programs"))
    body = resp.content
    assert b"2025-2026" in body
    assert b"2026-2027" in body
    assert b"Public" in body
    assert b"Draft" in body


# --- Detail + publish toggle --------------------------------------------


@pytest.mark.django_db
def test_program_admin_detail_renders(client, pc_member, program):
    client.force_login(pc_member)
    resp = client.get(reverse("program_admin_detail", args=[program.academic_year]))
    assert resp.status_code == 200
    assert b"2030-2031" in resp.content


@pytest.mark.django_db
def test_program_admin_publish_toggle(client, pc_member, program):
    """POSTing the publish form flips the program's published flag."""
    assert program.published is False
    client.force_login(pc_member)
    resp = client.post(
        reverse("program_admin_detail", args=[program.academic_year]),
        {"published": "on"},
    )
    assert resp.status_code == 302
    program.refresh_from_db()
    assert program.published is True


@pytest.mark.django_db
def test_program_admin_detail_404s_for_unknown_year(client, pc_member):
    client.force_login(pc_member)
    resp = client.get(reverse("program_admin_detail", args=["2099-2100"]))
    assert resp.status_code == 404


# --- Event create + edit ------------------------------------------------


@pytest.mark.django_db
def test_program_admin_event_new_creates_event_attached_to_program(
    client, pc_member, program,
):
    client.force_login(pc_member)
    resp = client.post(
        reverse("program_admin_event_new", args=[program.academic_year]),
        {
            "title": "New Seminar",
            "slug":  "new-seminar",
            "event_type": "seminar",
            "start_date": "2030-09-01",
            "end_date":   "2031-05-01",
            "format":     "online",
            "status":     "draft",
            "description": "test",
            "access_info": "",
            "faculty":    [],
        },
    )
    assert resp.status_code == 302
    e = Event.objects.get(slug="new-seminar")
    assert e.program == program
    assert e.event_type == Event.Type.SEMINAR


@pytest.mark.django_db
def test_program_admin_event_new_rejects_non_program_event_type(
    client, pc_member, program,
):
    """PC admin's event form restricts type to annual-program types."""
    client.force_login(pc_member)
    resp = client.post(
        reverse("program_admin_event_new", args=[program.academic_year]),
        {
            "title": "Special",
            "slug":  "special-x",
            "event_type": "special_event",  # not allowed
            "start_date": "2030-09-01",
            "end_date":   "2031-05-01",
            "format":     "online",
            "status":     "draft",
            "description": "test",
            "access_info": "",
            "faculty":    [],
        },
    )
    assert resp.status_code == 200  # form re-renders with errors
    assert not Event.objects.filter(slug="special-x").exists()


@pytest.mark.django_db
def test_program_admin_event_edit_updates_existing(client, pc_member, program):
    e = Event.objects.create(
        title="Original", slug="original-seminar",
        event_type=Event.Type.SEMINAR,
        start_date=date(2030, 9, 1), end_date=date(2031, 5, 1),
        program=program,
    )
    client.force_login(pc_member)
    resp = client.post(
        reverse("program_admin_event_edit", args=[program.academic_year, e.slug]),
        {
            "title": "Renamed",
            "slug":  "original-seminar",
            "event_type": "seminar",
            "start_date": "2030-09-01",
            "end_date":   "2031-05-01",
            "format":     "online",
            "status":     "draft",
            "description": "edited",
            "access_info": "",
            "faculty":    [],
        },
    )
    assert resp.status_code == 302
    e.refresh_from_db()
    assert e.title == "Renamed"
    assert e.description == "edited"


@pytest.mark.django_db
def test_program_admin_event_edit_404s_when_event_not_in_this_program(
    client, pc_member, program,
):
    other_program = Program.objects.create(academic_year="2031-2032")
    e = Event.objects.create(
        title="Elsewhere", slug="elsewhere",
        event_type=Event.Type.SEMINAR,
        start_date=date(2031, 9, 1), end_date=date(2032, 5, 1),
        program=other_program,
    )
    client.force_login(pc_member)
    resp = client.get(
        reverse("program_admin_event_edit", args=[program.academic_year, e.slug])
    )
    assert resp.status_code == 404
