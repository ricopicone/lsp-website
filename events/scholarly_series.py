"""The Scholarly Seminar Series page's fixed content (task #851).

The series ran before the site did. Talks given since are events of type
``scholarly_seminar`` and list themselves; ``HISTORY`` is the talks before
that, as Sheila Cavanagh, who created the series, listed them (2026-10-27).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class PastTalk:
    date: dt.date
    presenter: str
    title: str


HISTORY = (
    PastTalk(dt.date(2024, 2, 3), "Shanna Carlson de la Torre, PhD",
             "Femininity and the Spirit of Decision"),
    PastTalk(dt.date(2024, 6, 8), "Matt Lovett, PhD and Psychoanalytic Candidate",
             "Demanding the Real of Sexual Difference: On Recent Lacanian "
             "Transphobia and Beyond"),
    PastTalk(dt.date(2024, 9, 21), "Christopher Meyer",
             "Working through and from the object of the fundamental fantasy in "
             "the after-words of the clinic of addiction"),
    PastTalk(dt.date(2024, 10, 5), "Annie Rogers, PhD and Psychoanalyst",
             "After Words: A poetics and logic of the unconscious in a novel"),
    PastTalk(dt.date(2025, 2, 22), "Chris Vanderwees, PhD, RP and psychoanalyst",
             "Dwelling on the Direction of the Treatment for the Unhoused Subject"),
    PastTalk(dt.date(2025, 5, 31), "Shanna Carlson, PhD",
             "Georges Bataille Extends a Sprig of Life: Language, Experience, and "
             "the Out-of-Language"),
    PastTalk(dt.date(2026, 3, 7), "Diana Cuello, PhD",
             "The Perpetual Writing of the Dream"),
)


def coordinators() -> list:
    """Who holds the Scholarly Seminar Series Coordinator role, for the page:
    the description is introduced in their name, their bio sits beside it, and
    proposals go to them by way of their directory profile."""
    from accounts.models import User
    from core.models import StaffRole

    return list(
        User.objects.filter(
            is_active=True,
            staff_roles__key=StaffRole.SCHOLARLY_SEMINAR_COORDINATOR,
        ).select_related("profile").order_by("last_name", "first_name")
    )


def presenters(event) -> str:
    """The names of an event's presenters, members first, for a listing."""
    names = [u.get_full_name() for u in event.member_speakers.all()]
    names += [s.name for s in event.speakers.all() if s.public]
    return ", ".join(n for n in names if n)
