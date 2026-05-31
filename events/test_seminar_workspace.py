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


def test_get_or_create_workgroup_is_idempotent_and_seminar_kind():
    event = _seminar()
    wg = event.get_or_create_workgroup()
    assert wg.kind == wg.Kind.SEMINAR
    assert wg.has_works is False          # seminar capability seed
    assert event.get_or_create_workgroup() == wg   # idempotent


def test_workgroup_kind_follows_event_type():
    """Stopgap: a reading-group event's workspace is a reading_group workgroup,
    not a seminar (so /groups/reading-groups/ populates)."""
    rg = Event.objects.create(
        title="Reading Lacan's Seminar XI", slug="reading-xi",
        event_type=Event.Type.READING_GROUP,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
    )
    wg = rg.get_or_create_workgroup()
    assert wg.kind == wg.Kind.READING_GROUP


def test_creating_workspace_provisions_a_channel():
    event = _seminar()
    wg = event.get_or_create_workgroup()
    assert wg.channels.first() is not None
    assert wg.channels.first().category.name == "Seminars"


def test_roster_derives_from_faculty_and_paid_registrants():
    event = _seminar()
    wg = event.get_or_create_workgroup()

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
    wg = event.get_or_create_workgroup()
    ch = wg.channels.first()
    assert ch.access == Channel.Access.WORKGROUP

    paid = _user("paid@x.test")
    _register(paid, event, status=Registration.Status.PAID)
    stranger = _user("stranger@x.test")
    assert channel_visible(ch, paid) is True
    assert channel_visible(ch, stranger) is False
