"""The review loop covers program events with no originating proposal (task #812).

The 2026–27 program was script-imported, so none of its offerings has an
approved ``EventProposal`` — and the review loop used to require one, so their
title, description, readings, fee note and price (billing mode included) all
changed with no Program Committee step. A program offering is on the program
because the committee put it there; that is the approval the loop protects.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.urls import reverse

from accounts.models import User
from events.models import Event, EventChangeRequest, Program


@pytest.fixture
def program(db):
    return Program.objects.create(academic_year="2031-2032", published=True)


def _event(program, **kw):
    defaults = dict(
        title="Imported Seminar", slug="imported-seminar",
        description="The description the committee published.",
        event_type=Event.Type.SEMINAR,
        start_date=date(2031, 9, 1), end_date=date(2032, 5, 1),
        published=True, status=Event.Status.OPEN, program=program,
    )
    defaults.update(kw)
    return Event.objects.create(**defaults)


@pytest.mark.parametrize("event_type", [Event.Type.SEMINAR, Event.Type.READING_GROUP])
def test_imported_program_offering_requires_review(program, event_type):
    assert _event(program, event_type=event_type).requires_change_review() is True


def test_publication_cascades_from_the_program(program):
    """A program event's visibility is its Program's (task #532), so a
    PC-created event whose own ``published`` flag was never set is still under
    review once the program is public — and not before."""
    event = _event(program, published=False)
    assert event.requires_change_review() is True

    program.published = False
    program.save()
    event.refresh_from_db()
    assert event.requires_change_review() is False


def test_cartel_stays_out(program):
    """Cartels are program events but not offerings the PC approved content for."""
    assert _event(program, event_type=Event.Type.CARTEL).requires_change_review() is False


def test_proposal_less_special_event_stays_out(db):
    """Special events are not on a program; without a proposal they edit freely
    as before."""
    event = Event.objects.create(
        title="Special", slug="special", event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2031, 10, 1), end_date=date(2031, 10, 1),
        published=True, status=Event.Status.OPEN,
    )
    assert event.requires_change_review() is False


def test_faculty_edit_to_an_imported_offering_shows_the_dialog(client, program):
    event = _event(program)
    fac = User.objects.create_user(email="fac@example.com")
    fac.profile.is_faculty = True
    fac.profile.save()
    event.add_faculty(fac)
    client.force_login(fac)

    resp = client.post(reverse("events:edit", args=[event.slug]), {
        "title": event.title,
        "description": "Rewritten from top to bottom by the faculty member.",
        "readings": "", "schedule_note": "", "contact": "", "fee_note": "",
    })

    assert resp.status_code == 200
    assert b"How substantial is this change" in resp.content
    event.refresh_from_db()
    assert event.description == "The description the committee published."

    # Submitting it for review holds the live page as it was.
    resp = client.post(reverse("events:edit", args=[event.slug]), {
        "title": event.title,
        "description": "Rewritten from top to bottom by the faculty member.",
        "readings": "", "schedule_note": "", "contact": "", "fee_note": "",
        "decision": "review",
    })
    assert resp.status_code == 302
    cr = EventChangeRequest.objects.get(event=event)
    assert cr.status == EventChangeRequest.Status.PENDING
    assert cr.original_description == "The description the committee published."
    event.refresh_from_db()
    assert event.description == "The description the committee published."
