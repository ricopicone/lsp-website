"""PC-admin bulk open/close registration for a whole program."""

from __future__ import annotations

from datetime import date

import pytest
from django.urls import reverse

from accounts.models import User
from committees.models import Committee
from events.models import Event, Program


@pytest.fixture
def pc_member(db):
    u = User.objects.create_user(email="pc2@x.test", password="x")
    committee, _ = Committee.objects.get_or_create(
        slug="programming-committee",
        defaults={"name": "Programming Committee"},
    )
    committee.add_member(u, start_date=date(2026, 1, 1))
    return u


@pytest.fixture
def program_with_events(db):
    program = Program.objects.create(academic_year="2031-2032", published=True)
    def mk(slug, status):
        return Event.objects.create(
            title=slug, slug=slug, program=program, status=status, published=True,
            start_date=date(2031, 9, 1), end_date=date(2032, 6, 1),
        )
    return program, [
        mk("bulk-a", Event.Status.DRAFT),
        mk("bulk-b", Event.Status.DRAFT),
        mk("bulk-c", Event.Status.OPEN),
        mk("bulk-d", Event.Status.CLOSED),
    ]


@pytest.mark.django_db
def test_bulk_open_flips_only_drafts(client, pc_member, program_with_events):
    program, (a, b, c, d) = program_with_events
    client.force_login(pc_member)
    resp = client.post(
        reverse("program_admin_registration_bulk", args=[program.academic_year]),
        {"action": "open"},
    )
    assert resp.status_code == 302
    for e in (a, b, c):
        e.refresh_from_db()
        assert e.status == Event.Status.OPEN
    d.refresh_from_db()
    assert d.status == Event.Status.CLOSED  # closed stays closed


@pytest.mark.django_db
def test_bulk_close_flips_only_open(client, pc_member, program_with_events):
    program, (a, b, c, d) = program_with_events
    client.force_login(pc_member)
    client.post(
        reverse("program_admin_registration_bulk", args=[program.academic_year]),
        {"action": "close"},
    )
    a.refresh_from_db()
    c.refresh_from_db()
    assert a.status == Event.Status.DRAFT  # drafts untouched
    assert c.status == Event.Status.CLOSED


@pytest.mark.django_db
def test_bulk_action_gated(client, program_with_events):
    program, events = program_with_events
    u = User.objects.create_user(email="nobody@x.test", password="x")
    client.force_login(u)
    resp = client.post(
        reverse("program_admin_registration_bulk", args=[program.academic_year]),
        {"action": "open"},
    )
    assert resp.status_code == 404
    events[0].refresh_from_db()
    assert events[0].status == Event.Status.DRAFT
