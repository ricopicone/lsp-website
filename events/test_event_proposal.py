"""Tests for the M12.5 faculty seminar-proposal flow."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from accounts.models import Profile, User
from committees.models import Committee
from events.models import Audience, Event, EventProposal, PriceTier
from registrations.models import Registration
from workgroups.models import Workgroup

pytestmark = pytest.mark.django_db


def _faculty(email="fac@x.test"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.is_faculty = True
    u.profile.save()
    return u


def _member(email="member@x.test"):
    """An LSP member who is NOT (yet) faculty."""
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    return u


def _pc_member(email="pc@x.test"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    Committee.objects.get(slug="programming-committee").add_member(u)
    return u


def _future(start_days=30, end_days=200):
    today = dt.date.today()
    return today + dt.timedelta(days=start_days), today + dt.timedelta(days=end_days)


def _register(user, event):
    tier = event.price_tiers.first() or PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("0.00")
    )
    return Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("0.00"), status=Registration.Status.PAID,
    )


def test_propose_open_to_any_member_not_outsiders(client):
    # Any LSP member may propose (teaching is what makes you faculty, not a
    # prerequisite for proposing).
    client.force_login(_member())
    assert client.get("/propose/").status_code == 200
    # A non-member (external role) may not.
    outsider = User.objects.create_user(email="ext@x.test", password="x")
    client.force_login(outsider)
    assert client.get("/propose/").status_code == 404


def test_approving_seminar_confers_faculty_on_instructors(client):
    member = _member("teacher@x.test")
    assert member.profile.is_faculty is False
    start, end = _future()
    p = EventProposal.objects.create(
        proposed_by=member, title="First Seminar", start_date=start, end_date=end,
    )
    p.faculty.add(member)
    p.approve(_pc_member())
    member.profile.refresh_from_db()
    assert member.profile.is_faculty is True   # teaching a seminar made them faculty


def test_propose_creates_proposal(client):
    fac = _faculty()
    start, end = _future()
    client.force_login(fac)
    resp = client.post("/propose/", {
        "event_type": Event.Type.SEMINAR,
        "title": "Reading Seminar XI",
        "description": "Four fundamental concepts.",
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "format": Event.Format.ONLINE,
    })
    assert resp.status_code == 302
    p = EventProposal.objects.get(title="Reading Seminar XI")
    assert p.proposed_by == fac and p.status == EventProposal.Status.PROPOSED


def test_approve_mints_new_standing_seminar(client):
    fac = _faculty()
    start, end = _future()
    p = EventProposal.objects.create(
        proposed_by=fac, title="A New Seminar", start_date=start, end_date=end,
        format=Event.Format.ONLINE,
    )
    p.faculty.add(fac)
    client.force_login(_pc_member())
    resp = client.post(f"/program-admin/proposals/{p.pk}/decide/", {"decision": "approve"})
    assert resp.status_code == 302
    p.refresh_from_db()
    assert p.status == EventProposal.Status.APPROVED
    event = p.minted_event
    assert event is not None and event.event_type == Event.Type.SEMINAR
    assert event.program.academic_year == p.academic_year
    wg = event.workgroup
    assert wg is not None and wg.kind == Workgroup.Kind.SEMINAR
    assert event.is_faculty(fac)              # faculty seeded onto the workgroup
    assert wg.current_term() == event          # the minted event is the active term


def test_approve_continuing_seminar_adds_term_and_lapses_prior(client):
    fac = _faculty()
    pc = _pc_member()
    # First term (past) of an existing seminar, with a paid student.
    first = EventProposal.objects.create(
        proposed_by=fac, title="Ongoing Seminar",
        start_date=dt.date(2024, 9, 1), end_date=dt.date(2025, 5, 1),
    )
    first_event = first.approve(pc)
    wg = first_event.workgroup
    student = User.objects.create_user(email="stud@x.test", password="x")
    student.profile.role = Profile.Role.ANALYST
    student.profile.save()
    _register(student, first_event)
    assert wg.has_archive_access(student) is True

    # Continuing term (future) attached to the same standing workgroup.
    start, end = _future()
    cont = EventProposal.objects.create(
        proposed_by=fac, title="Ongoing Seminar 2026",
        start_date=start, end_date=end, continues_seminar=wg,
    )
    new_event = cont.approve(pc)
    assert new_event.workgroup_id == wg.id        # same standing group, new term
    assert wg.current_term() == new_event
    # The prior-term student is archive-only until they re-enroll.
    assert wg.is_member(student) is False
    assert wg.has_archive_access(student) is True


def test_decline_then_resubmit(client):
    fac = _faculty()
    start, end = _future()
    p = EventProposal.objects.create(
        proposed_by=fac, title="Maybe Seminar", start_date=start, end_date=end,
    )
    client.force_login(_pc_member())
    client.post(f"/program-admin/proposals/{p.pk}/decide/",
                {"decision": "decline", "note": "Sharpen the focus."})
    p.refresh_from_db()
    assert p.status == EventProposal.Status.DECLINED and "Sharpen" in p.review_note

    client.force_login(fac)
    resp = client.post(f"/propose/{p.pk}/edit/", {
        "event_type": Event.Type.SEMINAR,
        "title": "Maybe Seminar v2", "start_date": start.isoformat(),
        "end_date": end.isoformat(), "format": Event.Format.ONLINE,
    })
    assert resp.status_code == 302
    p.refresh_from_db()
    assert p.status == EventProposal.Status.PROPOSED and p.title == "Maybe Seminar v2"


def test_form_rejects_end_before_start(client):
    fac = _faculty()
    start, _ = _future()
    client.force_login(fac)
    resp = client.post("/propose/", {
        "event_type": Event.Type.SEMINAR,
        "title": "Bad Dates", "start_date": start.isoformat(),
        "end_date": (start - dt.timedelta(days=5)).isoformat(),
        "format": Event.Format.ONLINE,
    })
    assert resp.status_code == 200                 # re-rendered with errors
    assert not EventProposal.objects.filter(title="Bad Dates").exists()


def test_decide_gated_to_pc(client):
    fac = _faculty()
    start, end = _future()
    p = EventProposal.objects.create(
        proposed_by=fac, title="Gate Test", start_date=start, end_date=end,
    )
    client.force_login(_faculty("other@x.test"))   # faculty, but not PC
    assert client.post(f"/program-admin/proposals/{p.pk}/decide/",
                       {"decision": "approve"}).status_code == 404
    p.refresh_from_db()
    assert p.status == EventProposal.Status.PROPOSED


# ---- generalized proposals: reading group + special event (M12.5) ----

def test_approve_reading_group_mints_own_workgroup_with_organizer():
    member = _member("rgorg@x.test")
    start, end = _future()
    p = EventProposal.objects.create(
        proposed_by=member, title="Écrits Reading Group",
        event_type=Event.Type.READING_GROUP,
        start_date=start, end_date=end, format=Event.Format.ONLINE,
    )
    event = p.approve(_pc_member())
    assert event.event_type == Event.Type.READING_GROUP
    assert event.status == Event.Status.OPEN
    wg = event.workgroup
    assert wg is not None and wg.kind == Workgroup.Kind.READING_GROUP
    # The proposer becomes an organizer of the group's own workgroup.
    m = wg.memberships.get(user=member)
    assert m.role == m.Role.ORGANIZER
    assert event.is_faculty(member) is False  # reading groups don't confer faculty


def test_approve_special_event_drafts_and_never_leaks_into_pc():
    """A special-event proposal mints a DRAFT linked to the PC workgroup for
    provenance only — the proposer must NOT become a PC member (the leak guard)."""
    member = _member("seorg@x.test")
    start, end = _future(start_days=40, end_days=40)
    p = EventProposal.objects.create(
        proposed_by=member, title="Working with the Negative",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=start, end_date=end, format=Event.Format.ONLINE,
    )
    p.faculty.add(member)  # even if listed, must not join the PC roster
    event = p.approve(_pc_member())
    assert event.event_type == Event.Type.SPECIAL_EVENT
    assert event.status == Event.Status.DRAFT          # PC finalizes before publishing
    assert event.program is None                       # one-off, not in a program
    pc_wg = Committee.objects.get(slug="programming-committee").workgroup
    assert event.workgroup_id == pc_wg.id              # provenance link only
    assert pc_wg.is_member(member) is False            # the leak guard
    assert member not in [m.user for m in pc_wg.memberships.all()]


def test_member_can_open_propose_page(client):
    client.force_login(_member("opener@x.test"))
    assert client.get("/propose/").status_code == 200


def test_outsider_cannot_open_propose_page(client):
    outsider = User.objects.create_user(email="aud@x.test", password="x")
    outsider.profile.role = Profile.Role.EXTERNAL
    outsider.profile.save()
    client.force_login(outsider)
    assert client.get("/propose/").status_code == 404


# ---- type-aware form: readings, special-event fields, validation ----

def test_proposal_parses_readings_into_rows(client):
    fac = _faculty("reads@x.test")
    start, end = _future()
    client.force_login(fac)
    resp = client.post("/propose/", {
        "event_type": Event.Type.SEMINAR, "title": "With Readings",
        "description": "x", "start_date": start.isoformat(),
        "end_date": end.isoformat(), "format": Event.Format.ONLINE,
        "readings_text": "Freud, S. The Interpretation of Dreams.\n\nLacan, J. Écrits.\n",
    })
    assert resp.status_code == 302
    p = EventProposal.objects.get(title="With Readings")
    citations = list(p.readings.values_list("citation", flat=True))
    assert citations == [
        "Freud, S. The Interpretation of Dreams.", "Lacan, J. Écrits.",
    ]  # blank line dropped, order preserved


def test_special_event_proposal_allows_tbd_date(client):
    member = _member("tbd@x.test")
    client.force_login(member)
    resp = client.post("/propose/", {
        "event_type": Event.Type.SPECIAL_EVENT, "title": "TBD Talk",
        "description": "A talk, date to come.", "date_tbd": "on",
        "format": Event.Format.ONLINE,
        "external_speakers": "Jane Doe — jane@x.test — analyst, Paris",
        "speaker_arrangement": "pc",
    })
    assert resp.status_code == 302
    p = EventProposal.objects.get(title="TBD Talk")
    assert p.date_tbd is True and p.start_date is None
    assert p.speaker_arrangement == "pc"


def test_special_event_requires_date_unless_tbd(client):
    member = _member("nodate@x.test")
    client.force_login(member)
    resp = client.post("/propose/", {
        "event_type": Event.Type.SPECIAL_EVENT, "title": "No Date",
        "description": "x", "format": Event.Format.ONLINE,
    })
    assert resp.status_code == 200  # re-rendered with an error
    assert not EventProposal.objects.filter(title="No Date").exists()
