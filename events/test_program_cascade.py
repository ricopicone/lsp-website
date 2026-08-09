"""The visibility cascade for annual-program events (task #532).

A seminar / reading group / cartel is public when its Program is public — its
own ``published`` flag is not the lever. Only ``Event.is_public_now`` honored
that; the badge, the register gate, the listings, the landing page and the
calendar feed all read the raw flag, so a PC-created event read "Draft" while
being publicly visible. See
docs/superpowers/specs/2026-08-09-program-event-pricing-and-cascade-design.md
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.urls import reverse

from events.models import Audience, Event, PriceTier, Program

pytestmark = pytest.mark.django_db


def _program_event(*, program_published=True, event_published=False,
                   slug="cascade-seminar"):
    program, _ = Program.objects.get_or_create(
        academic_year="2026-2027", defaults={"published": program_published},
    )
    if program.published != program_published:
        program.published = program_published
        program.save(update_fields=["published"])
    today = dt.date.today()
    event = Event.objects.create(
        title="Cascade Seminar", slug=slug, event_type=Event.Type.SEMINAR,
        program=program, start_date=today + dt.timedelta(days=7),
        end_date=today + dt.timedelta(days=90),
        status=Event.Status.OPEN, published=event_published,
    )
    PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("100"),
        minimum_amount=Decimal("0"),
    )
    return event


def test_badge_follows_the_program_not_the_event_flag():
    event = _program_event(program_published=True, event_published=False)
    assert event.registration_badge["label"] == "Registration open"


def test_badge_reads_draft_when_the_program_is_unpublished():
    event = _program_event(program_published=False, event_published=False)
    assert event.registration_badge["label"] == "Draft"


def test_non_program_event_still_reads_its_own_flag():
    """A special event has no Program; ``published`` remains its lever."""
    today = dt.date.today()
    event = Event.objects.create(
        title="Special", slug="special-cascade",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=today + dt.timedelta(days=7),
        end_date=today + dt.timedelta(days=7),
        status=Event.Status.OPEN, published=False,
    )
    assert event.registration_badge["label"] == "Draft"
    event.published = True
    assert event.registration_badge["label"] == "Registration open"


def test_annual_type_without_a_program_falls_back_to_published():
    today = dt.date.today()
    event = Event.objects.create(
        title="Orphan", slug="orphan-cascade", event_type=Event.Type.SEMINAR,
        program=None, start_date=today + dt.timedelta(days=7),
        end_date=today + dt.timedelta(days=90),
        status=Event.Status.OPEN, published=True,
    )
    assert event.registration_badge["label"] == "Registration open"


def test_register_view_reachable_for_a_published_programs_event(
    client, django_user_model,
):
    event = _program_event(program_published=True, event_published=False)
    user = django_user_model.objects.create_user(
        email="member@example.com", password="pw",
    )
    client.force_login(user)
    response = client.get(reverse("registrations:register", args=[event.slug]))
    assert response.status_code == 200


def test_register_view_404s_when_the_program_is_unpublished(
    client, django_user_model,
):
    event = _program_event(program_published=False, event_published=False)
    user = django_user_model.objects.create_user(
        email="member2@example.com", password="pw",
    )
    client.force_login(user)
    response = client.get(reverse("registrations:register", args=[event.slug]))
    assert response.status_code == 404
