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

# Shared bits for every propose POST: submit intent (vs save), the location
# dropdown, and the external-speaker formset's management form.
_MGMT = {
    "action": "submit",
    "location_kind": "online_insite",
    "speakers-TOTAL_FORMS": "0", "speakers-INITIAL_FORMS": "0",
    "speakers-MIN_NUM_FORMS": "0", "speakers-MAX_NUM_FORMS": "1000",
}


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
        **_MGMT,
        "event_type": Event.Type.SEMINAR,
        "title": "Reading Seminar XI",
        "description": "Four fundamental concepts.",
        "start_date": start.isoformat(), "end_date": end.isoformat(),
    })
    assert resp.status_code == 302
    p = EventProposal.objects.get(title="Reading Seminar XI")
    assert p.proposed_by == fac and p.status == EventProposal.Status.PROPOSED


def test_approve_mints_new_standing_seminar(client):
    fac = _faculty()
    start, end = _future()
    p = EventProposal.objects.create(
        proposed_by=fac, title="A New Seminar", start_date=start, end_date=end,
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
        **_MGMT,
        "event_type": Event.Type.SEMINAR,
        "title": "Maybe Seminar v2", "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    })
    assert resp.status_code == 302
    p.refresh_from_db()
    assert p.status == EventProposal.Status.PROPOSED and p.title == "Maybe Seminar v2"


def test_form_rejects_end_before_start(client):
    fac = _faculty()
    start, _ = _future()
    client.force_login(fac)
    resp = client.post("/propose/", {
        **_MGMT,
        "event_type": Event.Type.SEMINAR,
        "title": "Bad Dates", "start_date": start.isoformat(),
        "end_date": (start - dt.timedelta(days=5)).isoformat(),
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
        start_date=start, end_date=end,
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


def test_approve_special_event_opens_and_never_leaks_into_pc():
    """A special-event proposal mints a real OPEN event (never a "draft"), linked
    to the PC workgroup for provenance only — the proposer must NOT become a PC
    member (the leak guard)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    member = _member("seorg@x.test")
    p = EventProposal.objects.create(
        proposed_by=member, title="Working with the Negative",
        event_type=Event.Type.SPECIAL_EVENT,
        proposed_datetime=datetime(2099, 5, 1, 19, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
    )
    p.faculty.add(member)  # even if listed, must not join the PC roster
    event = p.approve(_pc_member())
    assert event.event_type == Event.Type.SPECIAL_EVENT
    assert event.status == Event.Status.OPEN           # approved = a real event
    assert event.published is True                      # has a date → goes live
    assert event.program is None                       # one-off, not in a program
    pc_wg = Committee.objects.get(slug="programming-committee").workgroup
    assert event.workgroup_id == pc_wg.id              # provenance link only
    assert pc_wg.is_member(member) is False            # the leak guard
    assert member not in [m.user for m in pc_wg.memberships.all()]


def test_approve_tbd_special_event_stays_unpublished():
    p = EventProposal.objects.create(
        proposed_by=_member("tbd2@x.test"), title="Someday Talk",
        event_type=Event.Type.SPECIAL_EVENT, date_tbd=True,
    )
    event = p.approve(_pc_member())
    assert event.status == Event.Status.OPEN
    assert event.published is False  # no date yet → held until the PC sets one


def test_special_event_approve_mints_complete_event():
    """A fully-specified special-event proposal auto-mints a ready event: a
    session at the proposed time, a price tier, internal speakers as display-only
    member_speakers, and external speakers as Speaker rows."""
    from datetime import datetime
    from decimal import Decimal
    from zoneinfo import ZoneInfo

    from django.utils import timezone

    from events.models import ProposalSpeaker

    pacific = ZoneInfo("America/Los_Angeles")
    when = datetime(2099, 11, 1, 18, 0, tzinfo=pacific)
    insider = _faculty("insider@x.test")
    p = EventProposal.objects.create(
        proposed_by=_member("prop@x.test"), title="An Evening Lecture",
        event_type=Event.Type.SPECIAL_EVENT, proposed_datetime=when,
        location_kind=EventProposal.LocationKind.IN_PERSON,
        location="123 Rue Lacan, Paris",
        fee_amount=Decimal("25.00"), tuition_covers=False,
    )
    p.faculty.add(insider)
    ProposalSpeaker.objects.create(
        proposal=p, name="Dr. Externa", email="ex@x.test",
        affiliation="Paris", bio="Analyst.",
    )
    event = p.approve(_pc_member())

    session = event.sessions.get()
    assert timezone.localtime(session.start_at, pacific).hour == 18  # Pacific time kept
    assert event.start_date == when.date()
    tier = event.price_tiers.get()
    assert tier.base_amount == Decimal("25.00") and tier.covered_by_tuition is False
    assert event.format == Event.Format.IN_PERSON
    assert event.access_info == "123 Rue Lacan, Paris"       # venue carried
    assert insider in event.member_speakers.all()            # internal = display-only
    assert event.speakers.get().name == "Dr. Externa"        # external minted


def test_seminar_approve_builds_tuition_covered_tier():
    fac = _faculty("semfee@x.test")
    start, end = _future()
    p = EventProposal.objects.create(
        proposed_by=fac, title="Fee Seminar", event_type=Event.Type.SEMINAR,
        start_date=start, end_date=end, fee_amount=__import__("decimal").Decimal("150"),
        tuition_covers=True,
    )
    event = p.approve(_pc_member())
    tier = event.price_tiers.get()
    assert tier.covered_by_tuition is True  # tuition always covers offerings


def test_fee_type_sliding_keeps_only_the_range(client):
    """fee_type=sliding stores min/max and drops any stray fixed amount."""
    from decimal import Decimal
    fac = _faculty("slide@x.test")
    start, end = _future()
    client.force_login(fac)
    resp = client.post("/propose/", {
        **_MGMT, "event_type": Event.Type.SEMINAR, "title": "Sliding Sem",
        "description": "x", "start_date": start.isoformat(), "end_date": end.isoformat(),
        "fee_type": "sliding", "fee_amount": "999",  # fixed value must be discarded
        "fee_sliding_min": "0", "fee_sliding_max": "120",
    })
    assert resp.status_code == 302
    p = EventProposal.objects.get(title="Sliding Sem")
    assert p.fee_amount is None
    assert p.fee_sliding_min == Decimal("0") and p.fee_sliding_max == Decimal("120")


def test_fee_type_fixed_requires_amount(client):
    fac = _faculty("fixed@x.test")
    start, end = _future()
    client.force_login(fac)
    resp = client.post("/propose/", {
        **_MGMT, "event_type": Event.Type.SEMINAR, "title": "No Amount",
        "description": "x", "start_date": start.isoformat(), "end_date": end.isoformat(),
        "fee_type": "fixed",  # no fee_amount → invalid
    })
    assert resp.status_code == 200
    assert not EventProposal.objects.filter(title="No Amount").exists()


def test_fee_type_free_clears_amounts(client):
    fac = _faculty("free@x.test")
    start, end = _future()
    client.force_login(fac)
    resp = client.post("/propose/", {
        **_MGMT, "event_type": Event.Type.SEMINAR, "title": "Free Sem",
        "description": "x", "start_date": start.isoformat(), "end_date": end.isoformat(),
        "fee_type": "free", "fee_amount": "50",  # ignored
    })
    assert resp.status_code == 302
    p = EventProposal.objects.get(title="Free Sem")
    assert p.fee_amount is None and p.fee_sliding_min is None


# ---- save / manage proposals ----

def test_save_allows_incomplete_then_manage_lists_it(client):
    fac = _faculty("saver@x.test")
    client.force_login(fac)
    # Save with no dates (incomplete) — allowed because it's not a submission.
    resp = client.post("/propose/", {
        **_MGMT, "action": "save", "event_type": Event.Type.SEMINAR,
        "title": "Draft Seminar", "description": "wip",
    })
    assert resp.status_code == 302
    p = EventProposal.objects.get(title="Draft Seminar")
    assert p.status == EventProposal.Status.SAVED and p.start_date is None
    # It shows on the manage page.
    page = client.get("/propose/mine/")
    assert page.status_code == 200 and b"Draft Seminar" in page.content


def test_submit_incomplete_saved_proposal_is_blocked(client):
    fac = _faculty("blk@x.test")
    p = EventProposal.objects.create(
        proposed_by=fac, title="Needs Dates", event_type=Event.Type.SEMINAR,
        status=EventProposal.Status.SAVED,
    )
    client.force_login(fac)
    resp = client.post(f"/propose/{p.pk}/submit/")
    assert resp.status_code == 302  # bounced back to edit
    p.refresh_from_db()
    assert p.status == EventProposal.Status.SAVED  # not submitted


def test_submit_complete_saved_proposal(client):
    fac = _faculty("ok@x.test")
    start, end = _future()
    p = EventProposal.objects.create(
        proposed_by=fac, title="Ready", event_type=Event.Type.SEMINAR,
        start_date=start, end_date=end, status=EventProposal.Status.SAVED,
    )
    client.force_login(fac)
    assert client.post(f"/propose/{p.pk}/submit/").status_code == 302
    p.refresh_from_db()
    assert p.status == EventProposal.Status.PROPOSED


def test_delete_proposal_but_not_approved(client):
    fac = _faculty("del@x.test")
    saved = EventProposal.objects.create(
        proposed_by=fac, title="Trash Me", event_type=Event.Type.SEMINAR,
        status=EventProposal.Status.SAVED,
    )
    approved = EventProposal.objects.create(
        proposed_by=fac, title="Kept", event_type=Event.Type.SEMINAR,
        status=EventProposal.Status.APPROVED,
    )
    client.force_login(fac)
    client.post(f"/propose/{saved.pk}/delete/")
    client.post(f"/propose/{approved.pk}/delete/")
    assert not EventProposal.objects.filter(pk=saved.pk).exists()
    assert EventProposal.objects.filter(pk=approved.pk).exists()  # approved kept


def test_cannot_manage_others_proposals(client):
    owner = _faculty("owner@x.test")
    p = EventProposal.objects.create(
        proposed_by=owner, title="Mine", event_type=Event.Type.SEMINAR,
        status=EventProposal.Status.SAVED,
    )
    client.force_login(_member("intruder@x.test"))
    assert client.post(f"/propose/{p.pk}/delete/").status_code == 404
    assert client.post(f"/propose/{p.pk}/submit/").status_code == 404


def test_saved_proposals_hidden_from_pc_queue(client):
    fac = _faculty("hide@x.test")
    EventProposal.objects.create(
        proposed_by=fac, title="Still Saved", event_type=Event.Type.SEMINAR,
        status=EventProposal.Status.SAVED,
    )
    client.force_login(_pc_member())
    resp = client.get("/program-admin/proposals/")
    assert b"Still Saved" not in resp.content  # only submitted ones reach the PC


# ---- proposal meeting scheduler ----

def test_schedule_choice_set_persists_recurrence(client):
    fac = _faculty("schedset@x.test")
    start, end = _future()
    client.force_login(fac)
    resp = client.post("/propose/", {
        **_MGMT, "event_type": Event.Type.SEMINAR, "title": "Sched Sem",
        "description": "x", "start_date": start.isoformat(), "end_date": end.isoformat(),
        "schedule_choice": "set", "sched_frequency": "weekly",
        "sched_weekdays": ["MO", "WE"], "sched_start_time": "18:00",
        "sched_end_time": "20:00",
    })
    assert resp.status_code == 302
    p = EventProposal.objects.get(title="Sched Sem")
    assert p.schedule_tbd is False and p.sched_frequency == "weekly"
    assert p.sched_weekdays == "MO,WE"


def test_schedule_set_requires_times(client):
    fac = _faculty("schedreq@x.test")
    start, end = _future()
    client.force_login(fac)
    resp = client.post("/propose/", {
        **_MGMT, "event_type": Event.Type.SEMINAR, "title": "Bad Sched",
        "description": "x", "start_date": start.isoformat(), "end_date": end.isoformat(),
        "schedule_choice": "set", "sched_frequency": "weekly",
        "sched_weekdays": ["MO"],  # no times
    })
    assert resp.status_code == 200  # re-rendered with an error
    assert not EventProposal.objects.filter(title="Bad Sched").exists()


def test_seminar_schedule_materializes_meeting_series():
    import datetime as _dt
    fac = _faculty("mat@x.test")
    start, end = _future()  # future range so occurrences generate
    p = EventProposal.objects.create(
        proposed_by=fac, title="Weekly Sem", event_type=Event.Type.SEMINAR,
        start_date=start, end_date=end, schedule_tbd=False,
        sched_frequency="weekly", sched_weekdays="MO",
        sched_start_time=_dt.time(18, 0), sched_end_time=_dt.time(20, 0),
    )
    event = p.approve(_pc_member())
    series = event.workgroup.meeting_series.get()
    assert series.frequency == "weekly" and series.weekdays == "MO"
    assert series.start_date == start and series.end_date == end
    assert event.workgroup.meetings.exists()  # generate() created occurrences


def test_schedule_tbd_creates_no_series():
    fac = _faculty("notbd@x.test")
    start, end = _future()
    p = EventProposal.objects.create(
        proposed_by=fac, title="TBD Sem", event_type=Event.Type.SEMINAR,
        start_date=start, end_date=end, schedule_tbd=True,
    )
    event = p.approve(_pc_member())
    assert not event.workgroup.meeting_series.exists()


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
        **_MGMT,
        "event_type": Event.Type.SEMINAR, "title": "With Readings",
        "description": "x", "start_date": start.isoformat(),
        "end_date": end.isoformat(),
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
        "action": "submit", "location_kind": "online_insite",
        "speakers-TOTAL_FORMS": "1", "speakers-INITIAL_FORMS": "0",
        "speakers-MIN_NUM_FORMS": "0", "speakers-MAX_NUM_FORMS": "1000",
        "speakers-0-name": "Jane Doe", "speakers-0-email": "jane@x.test",
        "speakers-0-affiliation": "Analyst, Paris", "speakers-0-bio": "A bio.",
        "event_type": Event.Type.SPECIAL_EVENT, "title": "TBD Talk",
        "description": "A talk, date to come.", "date_tbd": "on",
        "speaker_arrangement": "pc",
    })
    assert resp.status_code == 302
    p = EventProposal.objects.get(title="TBD Talk")
    assert p.date_tbd is True and p.proposed_datetime is None
    assert p.speaker_arrangement == "pc"
    assert p.proposal_speakers.get().name == "Jane Doe"  # external speaker captured


def test_special_event_requires_date_unless_tbd(client):
    member = _member("nodate@x.test")
    client.force_login(member)
    resp = client.post("/propose/", {
        **_MGMT,
        "event_type": Event.Type.SPECIAL_EVENT, "title": "No Date",
        "description": "x",
    })
    assert resp.status_code == 200  # re-rendered with an error
    assert not EventProposal.objects.filter(title="No Date").exists()
