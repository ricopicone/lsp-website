"""Past standalone events have a home at /events/past/ (task #814).

/events/ lists only standalone events that haven't ended, and /program/ owns
the annual-program types, so an ended special event, Day of Assembly or
Working Day used to drop off every listing while its page lived on.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, User
from events.models import Event, Program

pytestmark = pytest.mark.django_db


def _event(slug, *, end, start=None, event_type=Event.Type.SPECIAL_EVENT,
           visibility=Event.Visibility.PUBLIC, **extra):
    return Event.objects.create(
        title=slug.replace("-", " ").title(), slug=slug, event_type=event_type,
        start_date=start or end, end_date=end, published=True,
        visibility=visibility, **extra,
    )


def _past(client):
    return client.get(reverse("events:past")).content.decode()


def test_an_ended_event_moves_from_upcoming_to_past(client):
    today = timezone.localdate()
    ended = _event("ended-yesterday", end=today - dt.timedelta(days=1))
    ends_today = _event("ends-today", end=today)

    upcoming = client.get(reverse("events:list")).content.decode()
    past = _past(client)

    assert ended.slug not in upcoming
    assert ended.slug in past
    # An event ending today is still upcoming, on the school's date (#571).
    assert ends_today.slug in upcoming
    assert ends_today.slug not in past


def test_program_types_stay_on_the_program(client):
    program = Program.objects.create(academic_year="2024-2025", published=True)
    seminar = _event("old-seminar", end=dt.date(2025, 5, 1),
                     event_type=Event.Type.SEMINAR, program=program)
    assert seminar.slug not in _past(client)


def test_unpublished_past_events_are_hidden(client):
    draft = _event("old-draft", end=dt.date(2025, 5, 1))
    draft.published = False
    draft.save(update_fields=["published"])
    assert draft.slug not in _past(client)


def test_members_only_past_events_need_a_member(client):
    hidden = _event("members-gathering", end=dt.date(2025, 5, 1),
                    event_type=Event.Type.DAY_OF_ASSEMBLY,
                    visibility=Event.Visibility.MEMBERS_ONLY)
    assert hidden.slug not in _past(client)

    member = User.objects.create_user(email="past-member@x.test")
    member.profile.role = Profile.Role.ANALYST
    member.profile.save()
    client.force_login(member)
    assert hidden.slug in _past(client)


def test_grouped_by_academic_year_newest_first(client):
    _event("fall-2024", end=dt.date(2024, 10, 5))
    _event("spring-2025", end=dt.date(2025, 4, 5))
    _event("fall-2025", end=dt.date(2025, 10, 5))

    response = client.get(reverse("events:past"))
    years = [label for label, _events in response.context["years"]]
    assert years == ["2025-2026", "2024-2025"]
    by_year = dict(response.context["years"])
    assert [e.slug for e in by_year["2024-2025"]] == ["spring-2025", "fall-2024"]

    body = response.content.decode()
    assert "AY 2025–2026" in body
    assert body.index("fall-2025") < body.index("spring-2025") < body.index("fall-2024")


def test_the_two_lists_link_to_each_other(client):
    assert reverse("events:past") in client.get(reverse("events:list")).content.decode()
    assert reverse("events:list") in _past(client)


def test_empty_upcoming_list_points_at_the_past(client):
    body = client.get(reverse("events:list")).content.decode()
    assert "No upcoming events." in body
    assert "See past events" in body


def test_empty_past_list(client):
    assert "No past events yet." in _past(client)
