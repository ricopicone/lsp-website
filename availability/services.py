"""Transition and reporting logic for analyst availability.

Everything that changes availability goes through :func:`set_availability` so
the interval invariant (one open span per analyst × function) holds no matter
the caller — yearly import, coordinator console, or member self-service. The
read helpers (:func:`current_status`, :func:`current_map`) and the credit
calculation (:func:`coverage_fraction`) round it out.
"""

from __future__ import annotations

import datetime as _dt
import re

from django.db import transaction
from django.utils import timezone

from events.models import academic_year_date_range, academic_year_of

from .models import AnalystFunction, AvailabilitySpan

_TOKEN = re.compile(r"\{(\w+)\}")


def render_template(text: str, context: dict) -> str:
    """Substitute ``{token}`` placeholders for keys present in ``context``.

    Unknown tokens (and any other braces) are left untouched, so a hand-edited
    reminder template can never crash a send. Mirrors the referrals helper.
    """
    return _TOKEN.sub(
        lambda m: str(context[m.group(1)]) if m.group(1) in context else m.group(0),
        text,
    )


def current_and_upcoming_ay(today: _dt.date | None = None) -> tuple[str, str]:
    """The current academic-year label and the next one (e.g. ('2025-2026',
    '2026-2027')) — the two windows the coverage report shows."""
    today = today or timezone.localdate()
    current = academic_year_of(today)
    start_year = int(current.partition("-")[0])
    upcoming = f"{start_year + 1}-{start_year + 2}"
    return current, upcoming

Status = AvailabilitySpan.Status

#: Roles the availability table applies to. Only Analysts of the School today;
#: Scholars are expected to join once the school has any (we'll add the role
#: here, and nothing else needs to change). Keyed by ``Profile.Role`` values.
AVAILABILITY_ROLES = frozenset({"analyst"})


def eligible_profiles():
    """Profiles the availability table covers — analyst-track members.

    The single gate for "who has an availability row": the import, the
    coordinator console, and the directory table all start here.
    """
    from accounts.models import Profile

    return Profile.objects.filter(role__in=AVAILABILITY_ROLES)


def is_eligible(profile) -> bool:
    """Whether ``profile``'s role makes it part of the availability table."""
    return profile.role in AVAILABILITY_ROLES


@transaction.atomic
def set_availability(
    profile,
    function: AnalystFunction,
    status: str,
    *,
    on_date: _dt.date | None = None,
    source: str = AvailabilitySpan.Source.ADMIN,
    by=None,
    note: str = "",
) -> AvailabilitySpan | None:
    """Record ``profile``'s ``status`` for ``function`` as of ``on_date``.

    Closes the current open span and opens a new one, preserving history. A
    no-op (returns the existing open span) when the status *and* note already
    match, so re-running an import doesn't churn the log. Returns the new (or
    unchanged) open span.
    """
    on_date = on_date or timezone.localdate()
    open_span = (
        AvailabilitySpan.objects.select_for_update()
        .filter(profile=profile, function=function, end_date__isnull=True)
        .first()
    )

    if open_span is not None:
        if open_span.status == status and open_span.note == note:
            return open_span  # nothing changed — leave the log untouched
        # Close the old span the day before the new one takes effect, but never
        # before it began (same-day changes close as a zero-length span).
        open_span.end_date = max(on_date - _dt.timedelta(days=1), open_span.start_date)
        open_span.save(update_fields=["end_date"])

    return AvailabilitySpan.objects.create(
        profile=profile,
        function=function,
        status=status,
        start_date=on_date,
        note=note,
        source=source,
        created_by=by,
    )


def current_status(profile, function: AnalystFunction) -> str:
    """``profile``'s current status for ``function`` (UNKNOWN if never set)."""
    span = (
        AvailabilitySpan.objects.filter(
            profile=profile, function=function, end_date__isnull=True
        )
        .only("status")
        .first()
    )
    return span.status if span else Status.UNKNOWN


def current_map(profile) -> dict[int, str]:
    """Map of ``{function_id: status}`` for ``profile``'s open spans.

    Only functions with an open span appear; callers default the rest to
    UNKNOWN. One query, suitable for rendering a directory row.
    """
    return {
        span.function_id: span.status
        for span in AvailabilitySpan.objects.filter(
            profile=profile, end_date__isnull=True
        ).only("function_id", "status")
    }


def coverage_fraction(
    profile,
    function: AnalystFunction,
    ay_label: str,
    *,
    as_of: _dt.date | None = None,
) -> float:
    """Fraction of academic year ``ay_label`` ``profile`` was YES for ``function``.

    This is the "credit" figure: 1.0 means available the whole year, 0.5 half
    of it. Counts only days with a YES status, intersected with the academic
    year's [start, end) window. Open spans accrue up to ``as_of`` (default
    today), so an upcoming year reads 0.0 until it begins and a current year
    reflects credit earned so far. Result is clamped to [0, 1].
    """
    as_of = as_of or timezone.localdate()
    win_start, win_end = academic_year_date_range(ay_label)
    total_days = (win_end - win_start).days
    if total_days <= 0:
        return 0.0

    covered = 0
    spans = AvailabilitySpan.objects.filter(
        profile=profile, function=function, status=Status.YES
    ).only("start_date", "end_date")
    for span in spans:
        start = max(span.start_date, win_start)
        end = span.end_date or as_of  # open span accrues only up to as_of
        end = min(end, win_end)
        if end > start:
            covered += (end - start).days

    return min(covered / total_days, 1.0)
