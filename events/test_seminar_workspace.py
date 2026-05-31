"""Stage 5 — seminar attaches a Workgroup; roster derived from the event."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

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
    event.faculty.add(teacher)
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
