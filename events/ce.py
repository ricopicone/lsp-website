"""Continuing-education credits (task #486).

The credit sentence is shared by the ``Event`` (what the public page shows) and
the ``EventProposal`` (the estimate the Programming Committee sees in its
queue), so the phrasing lives here rather than in either model.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models


class CECreditBasis(models.TextChoices):
    """Whether a credit count covers the whole event or each meeting.

    A one-day special event quotes a total; a year-long seminar quotes credits
    per meeting, since its total depends on how many meetings actually happen.
    """

    TOTAL = "total", "in total"
    PER_MEETING = "per_meeting", "per meeting"


def _plain(amount: Decimal) -> str:
    """``Decimal`` as a human would write it: 6.00 -> "6", 1.50 -> "1.5".

    ``normalize()`` alone turns 20.00 into 2E+1, so the result is formatted
    with ``:f`` to force plain notation.
    """
    return f"{amount.normalize():f}"


def credits_label(offers_ce: bool, credits: Decimal | None, basis: str) -> str:
    """The one-line CE sentence for an event, or "" when CE is off.

    An event can be marked as offering CE before the body has told the faculty
    member how many credits it carries, so a missing count is a normal state
    rather than an error.
    """
    if not offers_ce:
        return ""
    if credits is None:
        return "CE credits available."
    unit = "credit" if credits == 1 else "credits"
    suffix = " per meeting" if basis == CECreditBasis.PER_MEETING else ""
    return f"Approved for {_plain(credits)} CE {unit}{suffix}."
