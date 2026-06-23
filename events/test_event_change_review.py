"""Tests for the faculty editing review loop (task #295)."""

from __future__ import annotations

from datetime import date

import pytest
from django.urls import reverse

from accounts.models import User
from committees.models import Committee
from events.models import Event, EventChangeRequest, EventProposal

# ---- Fixtures ----------------------------------------------------------


@pytest.fixture
def approved_event(db):
    """A published seminar minted from an approved PC proposal — the only kind
    that carries the review expectation."""
    event = Event.objects.create(
        title="Seminar XI", slug="seminar-xi",
        description="The original body of the seminar description.",
        event_type=Event.Type.SEMINAR,
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
        published=True, status=Event.Status.OPEN,
    )
    EventProposal.objects.create(
        event_type=Event.Type.SEMINAR, title="Seminar XI",
        status=EventProposal.Status.APPROVED, minted_event=event,
    )
    return event


@pytest.fixture
def draft_event(db):
    """No originating proposal → edits apply freely."""
    return Event.objects.create(
        title="Free Event", slug="free-event",
        description="Body.", event_type=Event.Type.SEMINAR,
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
        published=True, status=Event.Status.OPEN,
    )


@pytest.fixture
def faculty_member(db, approved_event):
    u = User.objects.create_user(email="fac@example.com", first_name="Jane", last_name="Doe")
    u.profile.is_faculty = True
    u.profile.save()
    approved_event.add_faculty(u)
    return u


@pytest.fixture
def pc_member(db):
    u = User.objects.create_user(email="pc@example.com")
    Committee.objects.get(slug="programming-committee").add_member(
        u, start_date=date(2026, 1, 1)
    )
    return u


def _edit_url(event):
    return reverse("events:edit", args=[event.slug])


# ---- requires_change_review scope -------------------------------------


def test_approved_event_requires_review(approved_event):
    assert approved_event.requires_change_review() is True


def test_draft_event_does_not_require_review(draft_event):
    assert draft_event.requires_change_review() is False


def test_unpublished_approved_event_does_not_require_review(approved_event):
    approved_event.published = False
    approved_event.save()
    assert approved_event.requires_change_review() is False


# ---- The dialog --------------------------------------------------------


def test_content_change_shows_dialog_without_saving(client, approved_event, faculty_member):
    client.force_login(faculty_member)
    resp = client.post(_edit_url(approved_event), {
        "title": approved_event.title,
        "description": "A completely different description, fully rewritten.",
        "readings": "", "schedule_note": "", "contact": "", "fee_note": "",
    })
    assert resp.status_code == 200
    assert b"How substantial is this change" in resp.content
    approved_event.refresh_from_db()
    # Live event is untouched until the editor chooses.
    assert approved_event.description.startswith("The original body")


def test_nonreviewable_change_saves_immediately(client, approved_event, faculty_member):
    client.force_login(faculty_member)
    resp = client.post(_edit_url(approved_event), {
        "title": approved_event.title,
        "description": approved_event.description,
        "readings": "", "schedule_note": "Saturdays 9am", "contact": "", "fee_note": "",
    })
    assert resp.status_code == 302
    approved_event.refresh_from_db()
    assert approved_event.schedule_note == "Saturdays 9am"
    assert EventChangeRequest.objects.count() == 0


def test_certify_minor_applies_and_logs(client, approved_event, faculty_member):
    client.force_login(faculty_member)
    resp = client.post(_edit_url(approved_event), {
        "title": approved_event.title,
        "description": "Slightly tweaked body.",
        "readings": "", "schedule_note": "", "contact": "", "fee_note": "",
        "decision": "minor",
    })
    assert resp.status_code == 302
    approved_event.refresh_from_db()
    assert approved_event.description == "Slightly tweaked body."
    cr = EventChangeRequest.objects.get()
    assert cr.status == EventChangeRequest.Status.SELF_CERTIFIED
    assert cr.changed_fields == ["description"]
    assert cr.applied_at is not None


def test_submit_for_review_holds_change(client, approved_event, faculty_member):
    client.force_login(faculty_member)
    resp = client.post(_edit_url(approved_event), {
        "title": "Brand New Title",
        "description": approved_event.description,
        "readings": "", "schedule_note": "", "contact": "", "fee_note": "",
        "decision": "review",
    })
    assert resp.status_code == 302
    approved_event.refresh_from_db()
    assert approved_event.title == "Seminar XI"      # unchanged — held for review
    cr = EventChangeRequest.objects.get()
    assert cr.status == EventChangeRequest.Status.PENDING
    assert cr.changed_fields == ["title"]
    assert cr.proposed_title == "Brand New Title"
    assert cr.original_title == "Seminar XI"


def test_faculty_cannot_use_admin_option(client, approved_event, faculty_member):
    """A non-reviewer posting decision=admin falls back to self-certify."""
    client.force_login(faculty_member)
    client.post(_edit_url(approved_event), {
        "title": approved_event.title,
        "description": "Tweaked again.",
        "readings": "", "schedule_note": "", "contact": "", "fee_note": "",
        "decision": "admin",
    })
    cr = EventChangeRequest.objects.get()
    assert cr.status == EventChangeRequest.Status.SELF_CERTIFIED


def test_reviewer_admin_option_applies(client, approved_event, pc_member):
    client.force_login(pc_member)
    resp = client.post(_edit_url(approved_event), {
        "title": approved_event.title,
        "description": "Reworked by the committee directly.",
        "readings": "", "schedule_note": "", "contact": "", "fee_note": "",
        "decision": "admin",
    })
    assert resp.status_code == 302
    approved_event.refresh_from_db()
    assert approved_event.description == "Reworked by the committee directly."
    cr = EventChangeRequest.objects.get()
    assert cr.status == EventChangeRequest.Status.ADMINISTRATIVE
    assert cr.reviewed_by == pc_member


def test_reviewer_sees_admin_button(client, approved_event, pc_member):
    client.force_login(pc_member)
    resp = client.post(_edit_url(approved_event), {
        "title": approved_event.title,
        "description": "Different body for the dialog.",
        "readings": "", "schedule_note": "", "contact": "", "fee_note": "",
    })
    assert b"administrative change" in resp.content.lower()


# ---- PC review queue ---------------------------------------------------


@pytest.fixture
def pending_change(approved_event, faculty_member):
    return EventChangeRequest.objects.create(
        event=approved_event, proposed_by=faculty_member,
        status=EventChangeRequest.Status.PENDING,
        changed_fields=["description"],
        proposed_description="Approved new body.",
        original_description=approved_event.description,
    )


def test_pc_can_approve_change(client, approved_event, pending_change, pc_member):
    client.force_login(pc_member)
    resp = client.post(
        reverse("change_request_decide", args=[pending_change.pk]),
        {"decision": "approve"},
    )
    assert resp.status_code == 302
    pending_change.refresh_from_db()
    approved_event.refresh_from_db()
    assert pending_change.status == EventChangeRequest.Status.APPROVED
    assert approved_event.description == "Approved new body."


def test_pc_can_decline_change(client, approved_event, pending_change, pc_member):
    client.force_login(pc_member)
    resp = client.post(
        reverse("change_request_decide", args=[pending_change.pk]),
        {"decision": "decline", "note": "Too big a shift."},
    )
    assert resp.status_code == 302
    pending_change.refresh_from_db()
    approved_event.refresh_from_db()
    assert pending_change.status == EventChangeRequest.Status.DECLINED
    assert pending_change.review_note == "Too big a shift."
    assert approved_event.description.startswith("The original body")


def test_changes_queue_lists_pending(client, pending_change, pc_member):
    client.force_login(pc_member)
    resp = client.get(reverse("program_admin_changes"))
    assert resp.status_code == 200
    assert b"Seminar XI" in resp.content


def test_changes_queue_forbidden_to_random(client, db, pending_change):
    u = User.objects.create_user(email="rando@example.com")
    client.force_login(u)
    resp = client.get(reverse("program_admin_changes"))
    assert resp.status_code == 404
