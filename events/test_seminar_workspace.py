"""Stage 5 — seminar attaches a Workgroup; roster derived from the event."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import Profile, User
from events.models import Audience, Event, PriceTier
from parletre.models import Channel
from registrations.models import Registration

pytestmark = pytest.mark.django_db


def _user(email, is_faculty=False):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.is_faculty = is_faculty
    u.profile.save()
    return u


def _seminar(slug="sem"):
    return Event.objects.create(
        title="Seminar on the Letter", slug=slug,
        event_type=Event.Type.SEMINAR,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
    )


def _register(user, event, status=Registration.Status.PAID):
    tier = event.price_tiers.first() or PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("0.00")
    )
    return Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("0.00"), status=status,
    )


def test_ensure_workgroup_is_idempotent_and_seminar_kind():
    event = _seminar()
    wg = event.ensure_workgroup()
    assert wg.kind == wg.Kind.SEMINAR
    assert wg.has_works is False          # seminar capability seed
    assert event.ensure_workgroup() == wg   # idempotent


def test_workgroup_kind_follows_event_type():
    """A reading-group event's workspace is a reading_group workgroup, not a
    seminar (so /groups/reading-groups/ populates)."""
    rg = Event.objects.create(
        title="Reading Lacan's Seminar XI", slug="reading-xi",
        event_type=Event.Type.READING_GROUP,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
    )
    wg = rg.ensure_workgroup()
    assert wg.kind == wg.Kind.READING_GROUP


def test_pc_owned_event_links_to_pc_workgroup():
    """R3: a PC-organized event (assembly/work-day/special) links to the
    Programming Committee's workgroup, not a new offering group."""
    from committees.models import Committee

    pc = Committee.objects.get(slug="programming-committee")  # seeded + folded in
    special = Event.objects.create(
        title="Spring Day of Assembly", slug="doa-2026",
        event_type=Event.Type.DAY_OF_ASSEMBLY,
        start_date=date(2026, 4, 1), end_date=date(2026, 4, 1),
    )
    wg = special.ensure_workgroup()
    assert wg == pc.workgroup
    assert wg.kind == wg.Kind.COMMITTEE


def test_generate_event_links_event_to_workgroup():
    """R1: a Workgroup generates Events (Workgroup-primary direction)."""
    from workgroups.models import Workgroup

    wg = Workgroup.objects.create(kind=Workgroup.Kind.READING_GROUP, name="RG XI")
    e = wg.generate_event(
        slug="rg-xi-2026", start_date=date(2026, 9, 1), end_date=date(2027, 5, 1)
    )
    assert e.workgroup_id == wg.id
    assert e.event_type == Event.Type.READING_GROUP   # derived from kind
    assert e.title == "RG XI"
    assert list(wg.events.all()) == [e]


def test_is_member_spans_multiple_generated_events():
    """A recurring offering is one Workgroup with many Events (FK, not 1:1);
    membership in any linked event's roster counts."""
    from workgroups.models import Workgroup

    wg = Workgroup.objects.create(kind=Workgroup.Kind.SEMINAR, name="Recurring Seminar")
    wg.generate_event(slug="sem-2025", start_date=date(2025, 9, 1), end_date=date(2026, 5, 1))
    e2 = wg.generate_event(slug="sem-2026", start_date=date(2026, 9, 1), end_date=date(2027, 5, 1))
    u = _user("reg@x.test")
    _register(u, e2, status=Registration.Status.PAID)   # only in the 2026 offering
    assert wg.is_member(u) is True
    assert wg.is_member(_user("nobody@x.test")) is False


def test_creating_workspace_provisions_a_channel():
    event = _seminar()
    wg = event.ensure_workgroup()
    assert wg.channels.first() is not None
    assert wg.channels.first().category.name == "Seminars"


def test_roster_derives_from_faculty_and_paid_registrants():
    event = _seminar()
    wg = event.ensure_workgroup()

    teacher = _user("teacher@x.test", is_faculty=True)
    event.add_faculty(teacher)
    paid = _user("paid@x.test")
    _register(paid, event, status=Registration.Status.PAID)
    comped = _user("comped@x.test")
    _register(comped, event, status=Registration.Status.COMPED)
    awaiting = _user("awaiting@x.test")
    _register(awaiting, event, status=Registration.Status.AWAITING_PAYMENT)
    stranger = _user("stranger@x.test")

    assert wg.is_member(teacher) is True
    assert wg.is_member(paid) is True
    assert wg.is_member(comped) is True
    assert wg.is_member(awaiting) is False
    assert wg.is_member(stranger) is False

    # The unified roster (participants) shows faculty + paid/comped, deduped,
    # with no awaiting/stranger — students included so they get full tooling.
    roster = {p.user: p for p in wg.participants()}
    assert set(roster) == {teacher, paid, comped}
    assert roster[teacher].role == "faculty" and roster[teacher].is_lead
    assert roster[paid].membership is None       # derived, not a stored row
    assert roster[paid].role == "member"


def test_workspace_overview_shows_event_summary(client):
    """The seminar Workspace Overview renders the generated event's public
    summary (faculty + Register CTA) — same content as the event page."""
    event = _seminar()
    event.published = True
    event.status = Event.Status.OPEN
    event.save(update_fields=["published", "status"])
    wg = event.ensure_workgroup()

    teacher = _user("teach@x.test", is_faculty=True)
    teacher.first_name, teacher.last_name = "Jacques", "Lacan"
    teacher.save(update_fields=["first_name", "last_name"])
    event.add_faculty(teacher)

    client.force_login(teacher)
    resp = client.get(wg.get_absolute_url())
    assert resp.status_code == 200
    assert b"Jacques Lacan" in resp.content                 # faculty on Overview
    assert reverse("registrations:register", args=[event.slug]).encode() in resp.content


def test_workspace_shows_program_and_kind_breadcrumbs(client):
    """A seminar Workspace links back to BOTH its kind directory and its
    (visible) annual Program — stable context, not referrer-based."""
    from events.models import Program

    program = Program.objects.create(academic_year="2026-2027", published=True)
    event = _seminar()
    event.published = True
    event.status = Event.Status.OPEN
    event.program = program
    event.save(update_fields=["published", "status", "program"])
    wg = event.ensure_workgroup()

    resp = client.get(wg.get_absolute_url())
    assert resp.status_code == 200
    assert reverse("workgroups:kind_seminars").encode() in resp.content  # ← Seminars
    assert b"/program/?year=2026-2027" in resp.content                   # ← Program


def _published_seminar(slug, start, end):
    return Event.objects.create(
        title=f"Sem {slug}", slug=slug, event_type=Event.Type.SEMINAR,
        start_date=start, end_date=end, published=True, status=Event.Status.OPEN,
    )


def test_seminars_kind_list_grouped_by_ay_latest_first(client):
    older = _published_seminar("older", date(2025, 9, 1), date(2026, 5, 1))
    newer = _published_seminar("newer", date(2026, 9, 1), date(2027, 5, 1))
    older.ensure_workgroup()
    newer.ensure_workgroup()

    body = client.get("/groups/seminars/").content.decode()
    assert "2025-2026" in body and "2026-2027" in body
    assert body.index("2026-2027") < body.index("2025-2026")   # latest first
    assert "Registration open" in body                          # status badge


def test_registration_badge_states():
    from datetime import timedelta

    e = Event(published=False, status=Event.Status.DRAFT,
              start_date=date.today(), end_date=date.today())
    assert e.registration_badge["label"] == "Draft"
    e.published = True
    e.status = Event.Status.OPEN
    e.end_date = date.today() + timedelta(days=10)
    assert e.registration_badge["label"] == "Registration open"
    e.status = Event.Status.CLOSED
    assert e.registration_badge["label"] == "Registration closed"
    e.status = Event.Status.OPEN
    e.end_date = date.today() - timedelta(days=1)
    assert e.registration_badge["label"] == "Archived"


def test_requires_faculty_approval_defaults_off():
    e = _seminar()
    assert e.requires_faculty_approval is False


def test_event_url_redirects_to_workspace(client):
    """The standalone event URL 301/302s to the canonical Workspace."""
    event = _seminar()
    event.published = True
    event.status = Event.Status.OPEN
    event.save(update_fields=["published", "status"])
    wg = event.ensure_workgroup()
    resp = client.get(reverse("events:detail", args=[event.slug]))
    assert resp.status_code == 302 and resp.url == wg.get_absolute_url()


def test_published_seminar_workspace_shows_faculty_not_roster(client):
    """A seminar shows its faculty (via the event summary) but never a student
    roster — to anyone, including members."""
    event = _seminar()
    event.published = True
    event.status = Event.Status.OPEN
    event.save(update_fields=["published", "status"])
    wg = event.ensure_workgroup()
    teacher = _user("teach@x.test", is_faculty=True)
    teacher.first_name, teacher.last_name = "Jacques", "Lacan"
    teacher.save(update_fields=["first_name", "last_name"])
    event.add_faculty(teacher)

    student = _user("student@x.test")
    student.first_name, student.last_name = "Sabina", "Spielrein"
    student.save(update_fields=["first_name", "last_name"])
    _register(student, event, status=Registration.Status.PAID)

    # The roster is hidden for seminars — even from an enrolled member.
    assert wg.roster_visible_to(student) is False

    # Anonymous view: faculty shown, no student in any roster.
    resp = client.get(wg.get_absolute_url())
    assert resp.status_code == 200
    assert b"Jacques Lacan" in resp.content          # faculty shown
    assert b"Sabina Spielrein" not in resp.content   # student roster hidden


def test_draft_seminar_workspace_not_public(client):
    """An unpublished seminar's Workspace is NOT public (no leak before launch)."""
    event = _seminar()              # published defaults False
    wg = event.ensure_workgroup()
    assert client.get(wg.get_absolute_url()).status_code == 404


def test_paid_student_can_be_assigned_a_task(client):
    """A derived registrant (no stored membership row) is still a real
    participant: it shows in the assignee picker and can be assigned a task
    once the seminar workspace enables Tasks."""
    event = _seminar()
    wg = event.ensure_workgroup()
    wg.has_tasks = True
    wg.save(update_fields=["has_tasks"])

    student = _user("student@x.test")
    _register(student, event, status=Registration.Status.PAID)

    client.force_login(student)
    # The student (a member via payment) can add and self-assign a task.
    client.post(
        f"/groups/{wg.slug}/tasks/add/",
        {"title": "Read the seminar", "assignees": [student.pk]},
    )
    from workgroups.models import WorkgroupTask
    task = WorkgroupTask.objects.get(workgroup=wg)
    assert list(task.assignees.all()) == [student]

    # The picker offers the student even though there's no membership row.
    resp = client.get(f"{wg.get_absolute_url()}?tab=tasks")
    assert f'value="{student.pk}"'.encode() in resp.content


def test_seminar_channel_visible_to_registrant_not_to_stranger():
    from parletre.permissions import channel_visible

    event = _seminar()
    wg = event.ensure_workgroup()
    ch = wg.channels.first()
    assert ch.access == Channel.Access.WORKGROUP

    paid = _user("paid@x.test")
    _register(paid, event, status=Registration.Status.PAID)
    stranger = _user("stranger@x.test")
    assert channel_visible(ch, paid) is True
    assert channel_visible(ch, stranger) is False
