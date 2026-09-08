"""Faculty and conveners open and close registration themselves.

Until now ``Event.status`` could only be flipped from the Registrar console
(registrar StaffRole / Web Coordinator / serving PC) or the PC's bulk
per-program view, so the person actually running a seminar or reading group
had to ask someone else to close their own registration.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, User
from events.models import Event
from workgroups.models import WorkgroupMembership

pytestmark = pytest.mark.django_db


def _reading_group(status=Event.Status.OPEN, slug="freud-reading-group"):
    rg = Event.objects.create(
        title="Freud Reading Group", slug=slug,
        event_type=Event.Type.READING_GROUP,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
        published=True, status=status,
    )
    rg.ensure_workgroup()
    return rg


def _convener(event, email="convener@example.com"):
    """A convener as the proposal flow creates one: ORGANIZER on the offering's
    workgroup, with no FACULTY role anywhere (task #495)."""
    u = User.objects.create_user(email=email, password="x")
    WorkgroupMembership.objects.create(
        workgroup=event.workgroup, user=u,
        role=WorkgroupMembership.Role.ORGANIZER,
        start_date=timezone.localdate(),
    )
    return u


def _seminar(status=Event.Status.DRAFT, slug="seminar-on-the-letter"):
    ev = Event.objects.create(
        title="Seminar on the Letter", slug=slug,
        event_type=Event.Type.SEMINAR,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
        published=True, status=status,
    )
    ev.ensure_workgroup()
    return ev


def _faculty(event, email="faculty@example.com"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.is_faculty = True
    u.profile.save()
    WorkgroupMembership.objects.create(
        workgroup=event.workgroup, user=u,
        role=WorkgroupMembership.Role.FACULTY,
        start_date=timezone.localdate(),
    )
    return u


def _post(client, event, action, **extra):
    return client.post(
        reverse("events:registration_status", args=[event.slug]),
        {"action": action, **extra},
    )


# --- the mechanism -------------------------------------------------------


def test_set_registration_status_opens_a_closed_event():
    from events.registration_status import set_registration_status

    event = _reading_group(status=Event.Status.CLOSED)
    assert set_registration_status(event, "open") == Event.Status.OPEN
    event.refresh_from_db()
    assert event.status == Event.Status.OPEN


def test_set_registration_status_returns_none_for_a_no_op():
    """Closing an event that is already closed changes nothing and says so, so
    a caller can tell a real flip from a double-submitted button."""
    from events.registration_status import set_registration_status

    event = _reading_group(status=Event.Status.CLOSED)
    assert set_registration_status(event, "close") is None
    event.refresh_from_db()
    assert event.status == Event.Status.CLOSED


def test_set_registration_status_ignores_an_unknown_action():
    from events.registration_status import set_registration_status

    event = _reading_group(status=Event.Status.OPEN)
    assert set_registration_status(event, "delete") is None
    event.refresh_from_db()
    assert event.status == Event.Status.OPEN


# --- who may use it ------------------------------------------------------


def test_a_convener_closes_registration_for_their_reading_group(client):
    event = _reading_group()
    client.force_login(_convener(event))
    _post(client, event, "close")
    event.refresh_from_db()
    assert event.status == Event.Status.CLOSED


def test_a_convener_reopens_registration_for_their_reading_group(client):
    event = _reading_group(status=Event.Status.CLOSED)
    client.force_login(_convener(event))
    _post(client, event, "open")
    event.refresh_from_db()
    assert event.status == Event.Status.OPEN


def test_faculty_open_registration_on_their_draft_seminar(client):
    event = _seminar(status=Event.Status.DRAFT)
    client.force_login(_faculty(event))
    _post(client, event, "open")
    event.refresh_from_db()
    assert event.status == Event.Status.OPEN


def test_a_plain_member_may_not_change_registration_status(client):
    event = _reading_group()
    member = User.objects.create_user(email="member@example.com", password="x")
    WorkgroupMembership.objects.create(
        workgroup=event.workgroup, user=member,
        role=WorkgroupMembership.Role.MEMBER,
        start_date=timezone.localdate(),
    )
    client.force_login(member)
    assert _post(client, event, "close").status_code == 403
    event.refresh_from_db()
    assert event.status == Event.Status.OPEN


def test_a_get_cannot_change_registration_status(client):
    """Link scanners pre-click links; the flip lives behind the POST."""
    event = _reading_group()
    client.force_login(_convener(event))
    resp = client.get(reverse("events:registration_status", args=[event.slug]))
    assert resp.status_code == 405
    event.refresh_from_db()
    assert event.status == Event.Status.OPEN


def test_the_button_returns_you_to_the_page_you_pressed_it_on(client):
    event = _reading_group()
    client.force_login(_convener(event))
    back = f"{event.workgroup.get_absolute_url()}?tab=roster"
    resp = _post(client, event, "close", next=back)
    assert resp.status_code == 302
    assert resp.url == back


def test_an_offsite_next_is_refused(client):
    event = _reading_group()
    client.force_login(_convener(event))
    resp = _post(client, event, "close", next="https://evil.example.com/")
    assert resp.status_code == 302
    assert "evil.example.com" not in resp.url


# --- where it appears ----------------------------------------------------


def test_the_control_renders_on_the_event_edit_page(client):
    event = _reading_group()
    client.force_login(_convener(event))
    body = client.get(reverse("events:edit", args=[event.slug])).content.decode()
    assert "Close registration" in body


def test_the_control_renders_on_the_workspace_roster_tab(client):
    event = _reading_group()
    client.force_login(_convener(event))
    body = client.get(
        f"{event.workgroup.get_absolute_url()}?tab=roster"
    ).content.decode()
    assert "Close registration" in body


def test_the_settings_tab_points_at_the_control_without_carrying_it(client):
    """Settings edits the Workgroup, so it names the state and links to Edit
    event rather than growing an Event control of its own."""
    event = _reading_group()
    client.force_login(_convener(event))
    body = client.get(
        f"{event.workgroup.get_absolute_url()}?tab=settings"
    ).content.decode()
    assert "Registration for this reading group is open" in body
    assert "Close registration" not in body


def test_a_cartel_settings_tab_has_no_registration_note(client):
    """The note is gated on an offering with a primary event, so a cartel's
    Settings tab is untouched."""
    from cartels.models import Cartel

    lead = User.objects.create_user(email="lead@example.com", password="x")
    lead.profile.role = Profile.Role.ANALYST
    lead.profile.save()
    cartel = Cartel.objects.create_with_workgroup(name="Cartel of the Letter")
    wg = cartel.workgroup
    WorkgroupMembership.objects.create(
        workgroup=wg, user=lead, role=WorkgroupMembership.Role.MEMBER,
        start_date=timezone.localdate(),
    )
    client.force_login(lead)
    body = client.get(f"{wg.get_absolute_url()}?tab=settings").content.decode()
    assert "Registration for this" not in body
