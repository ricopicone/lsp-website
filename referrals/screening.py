"""Content screening for Find-an-Analyst submissions (task #479).

Referral request 26-0727 was a commodity form-spam bot: every visible text
input filled with a random mixed-case token, every checkbox checked. The
transport-level deterrents in ``accounts.antibot`` are the first line and
drop that class of bot outright; this module is the second, for anything
that gets past them.

Nothing here rejects. A hit puts the request in ``HELD`` for the
coordinator to release or mark junk, because every heuristic is fallible
and the cost of blocking a real person reaching out for an analyst is far
higher than the cost of a review click.
"""

from __future__ import annotations

#: Free-text fields short enough that a random token stands out. ``pronouns``
#: arrives already resolved through ``ReferralRequestForm.pronouns_display()``.
SCREENED_SHORT_FIELDS = ("name", "location", "language", "pronouns")

#: A token shorter than this is never judged — real names and languages are
#: often short, and there is no signal in "Ana" or "Urdu".
GIBBERISH_MIN_LENGTH = 8

#: Adjacent upper<->lower changes before a token reads as machine-generated.
#: Every junk token from 26-0727 scores 5 or more; every real value we hold
#: (Pittsburgh, Edmonton, English, Frankfurt, Bydgoszcz) scores 1, and the
#: nearest real-world miss, "MacDonald", scores 3.
GIBBERISH_MIN_CASE_TRANSITIONS = 4

#: Real narratives run 600-900 characters. 26-0727's was 21.
MIN_NARRATIVE_LENGTH = 40

#: Link spam is the other standard vector; real requesters do not paste URLs.
URL_MARKERS = ("http", "www.", "[url=", "<a ")


def count_case_transitions(value: str) -> int:
    """Adjacent letter pairs that change between upper and lower case."""
    return sum(
        1
        for a, b in zip(value, value[1:])
        if a.isalpha() and b.isalpha() and a.isupper() != b.isupper()
    )


def looks_like_gibberish(value: str) -> bool:
    """Whether a short free-text field reads as a machine-generated token.

    Only pure-alphabetic strings of at least ``GIBBERISH_MIN_LENGTH`` are
    candidates. The ``isalpha`` gate is load-bearing: it excludes anything
    with a space, digit, slash, comma, or hyphen, which is what keeps
    "they/them", "San Antonio Texas", and hyphenated surnames out.

    Vowel ratio was evaluated as a second signal and rejected — at any
    threshold that catches the junk it also flags "Pittsburgh" (0.20),
    "Frankfurt" (0.22), and "Bydgoszcz" (0.11). See the design doc.

    Known limit: an all-lowercase token ("qwrtplkjhg") scores zero
    transitions and is not caught here.
    """
    token = (value or "").strip()
    if len(token) < GIBBERISH_MIN_LENGTH or not token.isalpha():
        return False
    return count_case_transitions(token) >= GIBBERISH_MIN_CASE_TRANSITIONS


def _has_link(value: str) -> bool:
    lowered = (value or "").lower()
    return any(marker in lowered for marker in URL_MARKERS)


def screen(data: dict) -> str:
    """Judge one submission.

    Returns a short reason the coordinator can read at a glance, or ``""``
    when the submission looks fine. The reason doubles as the boolean, so
    callers just check truthiness.
    """
    for field in SCREENED_SHORT_FIELDS:
        value = (data.get(field) or "").strip()
        if looks_like_gibberish(value):
            return f"The {field} field looks machine-generated ({value!r})."

    for field in (*SCREENED_SHORT_FIELDS, "additional_information"):
        if _has_link(data.get(field) or ""):
            return f"The {field} field contains a link."

    narrative = (data.get("additional_information") or "").strip()
    if len(narrative) < MIN_NARRATIVE_LENGTH:
        return (
            f"The description is too short ({len(narrative)} characters); "
            f"real requests run to several hundred."
        )

    return ""
