"""Tests for the landing page's "Coming up" selection (task #461).

The rule: up to two standalone-type events starting within the next two months
are pinned above the chronological list, a true Special event first. See
docs/superpowers/specs/2026-07-23-pinned-special-events-design.md.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone

from accounts.models import Profile, User
from events.models import Event
from events.upcoming import landing_events


def _event(title, *, days, event_type=Event.Type.SEMINAR, span=0, **kwargs):
    """A published event starting ``days`` from today, running ``span`` days."""
    start = timezone.now().date() + timedelta(days=days)
    return Event.objects.create(
        title=title,
        slug=title.lower().replace(" ", "-"),
        event_type=event_type,
        start_date=start,
        end_date=start + timedelta(days=span),
        published=True,
        **kwargs,
    )


def _titles(user=None):
    return [e.title for e in landing_events(user or AnonymousUser())]


# --- Pinning ------------------------------------------------------------


@pytest.mark.django_db
def test_special_event_buried_by_seminars_is_pinned_to_the_top():
    """The case that prompted the feature: six seminars all start in the same
    stretch and push a special event off a four-item list."""
    for i in range(6):
        _event(f"Seminar {i}", days=10 + i)
    _event("Study Day", days=30, event_type=Event.Type.SPECIAL_EVENT)

    assert _titles()[0] == "Study Day"


@pytest.mark.django_db
def test_special_event_beyond_the_window_is_not_pinned():
    """Two months is the window; a special event past it sorts chronologically."""
    for i in range(3):
        _event(f"Seminar {i}", days=10 + i)
    _event("Distant Day", days=100, event_type=Event.Type.SPECIAL_EVENT)

    assert _titles() == ["Seminar 0", "Seminar 1", "Seminar 2", "Distant Day"]


@pytest.mark.django_db
def test_second_pin_goes_to_the_next_standalone_event():
    """A true Special event takes slot one even when a Working Day is sooner;
    the Working Day takes slot two."""
    for i in range(4):
        _event(f"Seminar {i}", days=10 + i)
    _event("Working Day", days=20, event_type=Event.Type.WORKING_DAY)
    _event("Study Day", days=40, event_type=Event.Type.SPECIAL_EVENT)

    assert _titles()[:2] == ["Study Day", "Working Day"]


@pytest.mark.django_db
def test_at_most_two_events_are_pinned():
    for i in range(4):
        _event(f"Seminar {i}", days=10 + i)
    _event("Study Day A", days=20, event_type=Event.Type.SPECIAL_EVENT)
    _event("Study Day B", days=25, event_type=Event.Type.SPECIAL_EVENT)
    _event("Study Day C", days=30, event_type=Event.Type.SPECIAL_EVENT)

    titles = _titles()
    assert titles[:2] == ["Study Day A", "Study Day B"]
    assert "Study Day C" not in titles


@pytest.mark.django_db
@pytest.mark.parametrize(
    "event_type",
    [Event.Type.SEMINAR, Event.Type.READING_GROUP, Event.Type.CARTEL],
)
def test_annual_program_types_are_never_pinned(event_type):
    for i in range(3):
        _event(f"Special {i}", days=1 + i, event_type=Event.Type.DAY_OF_ASSEMBLY)
    _event("Late Offering", days=30, event_type=event_type)

    assert _titles()[-1] == "Late Offering"


@pytest.mark.django_db
def test_pinned_event_is_not_repeated_in_the_chronological_list():
    _event("Seminar", days=30)
    _event("Study Day", days=10, event_type=Event.Type.SPECIAL_EVENT)

    titles = _titles()
    assert titles == ["Study Day", "Seminar"]


@pytest.mark.django_db
def test_pinned_events_are_flagged_for_the_template():
    _event("Seminar", days=10)
    _event("Study Day", days=20, event_type=Event.Type.SPECIAL_EVENT)

    events = landing_events(AnonymousUser())
    assert getattr(events[0], "pinned", False) is True
    assert getattr(events[1], "pinned", False) is False


@pytest.mark.django_db
def test_list_never_exceeds_the_limit():
    for i in range(6):
        _event(f"Seminar {i}", days=10 + i)
    _event("Study Day", days=20, event_type=Event.Type.SPECIAL_EVENT)

    assert len(landing_events(AnonymousUser())) == 4


# --- The rest of the list ------------------------------------------------


@pytest.mark.django_db
def test_drafts_and_past_events_are_excluded():
    _event("Past Talk", days=-10, event_type=Event.Type.SPECIAL_EVENT)
    draft = _event("Draft Day", days=10, event_type=Event.Type.SPECIAL_EVENT)
    Event.objects.filter(pk=draft.pk).update(published=False)
    _event("Seminar", days=20)

    assert _titles() == ["Seminar"]


@pytest.mark.django_db
def test_recently_started_seminar_still_surfaces_for_late_registration():
    """The pre-existing grace: a year-long seminar that began within the last
    month, and hasn't ended, still shows so late registration stays reachable."""
    _event("Started Seminar", days=-10, span=200)

    assert _titles() == ["Started Seminar"]


@pytest.mark.django_db
def test_recently_started_standalone_event_does_not_surface():
    """The grace is for seminars only — a special event that already began is
    over as far as the front page is concerned."""
    _event("Started Day", days=-10, span=200, event_type=Event.Type.SPECIAL_EVENT)

    assert _titles() == []


# --- Members-only visibility --------------------------------------------


@pytest.mark.django_db
def test_members_only_events_are_hidden_from_non_members():
    _event(
        "Members Study Day",
        days=20,
        event_type=Event.Type.SPECIAL_EVENT,
        visibility=Event.Visibility.MEMBERS_ONLY,
    )
    _event("Public Seminar", days=30)

    # Anonymous.
    assert _titles() == ["Public Seminar"]

    # An authenticated auditor (outside registrant) is not a member.
    auditor = User.objects.create_user(email="ext@example.com", password="x")
    assert _titles(auditor) == ["Public Seminar"]


@pytest.mark.django_db
def test_members_see_members_only_events_pinned():
    _event(
        "Members Study Day",
        days=20,
        event_type=Event.Type.SPECIAL_EVENT,
        visibility=Event.Visibility.MEMBERS_ONLY,
    )
    _event("Public Seminar", days=10)

    member = User.objects.create_user(email="m@example.com", password="x")
    member.profile.role = Profile.Role.ANALYST
    member.profile.save(update_fields=["role"])

    assert _titles(member) == ["Members Study Day", "Public Seminar"]
