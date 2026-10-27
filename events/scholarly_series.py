"""The Scholarly Seminar Series page's fixed content (task #851).

The series ran before the site did. Talks given since are events of type
``scholarly_seminar`` and list themselves; ``HISTORY`` is the talks before
that, as Sheila Cavanagh, who created the series, listed them (2026-10-27).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

#: Where presentation proposals go: the coordinator, by email, with a title
#: and a short abstract.
SUBMISSIONS_EMAIL = "sheilalcavanagh@gmail.com"


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


def presenters(event) -> str:
    """The names of an event's presenters, members first, for a listing."""
    names = [u.get_full_name() for u in event.member_speakers.all()]
    names += [s.name for s in event.speakers.all() if s.public]
    return ", ".join(n for n in names if n)
