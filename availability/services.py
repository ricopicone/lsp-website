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

from .models import AnalystFunction, AvailabilityNote, AvailabilitySpan

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

    return Profile.objects.filter(
        role__in=AVAILABILITY_ROLES,
        standing=Profile.Standing.ACTIVE,
        is_persona=False,
        user__is_active=True,
    )


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
) -> AvailabilitySpan | None:
    """Record ``profile``'s ``status`` for ``function`` as of ``on_date``.

    Closes the current open span and opens a new one, preserving history. A
    no-op (returns the existing open span) when the status already matches, so
    re-running an import doesn't churn the log. Returns the new (or unchanged)
    open span.
    """
    on_date = on_date or timezone.localdate()
    open_span = (
        AvailabilitySpan.objects.select_for_update()
        .filter(profile=profile, function=function, end_date__isnull=True)
        .first()
    )

    if open_span is not None:
        if open_span.status == status:
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
        source=source,
        created_by=by,
    )


def current_note(profile) -> str:
    """``profile``'s most recent availability note (empty string if none)."""
    note = profile.availability_notes.first()  # ordered -created_at
    return note.text if note else ""


def set_note(profile, text: str, *, by=None) -> AvailabilityNote | None:
    """Record a new availability note for ``profile`` if it differs from the
    current one (append-only, preserving history). Returns the new note, or
    None when unchanged."""
    text = (text or "").strip()[:300]
    if text == current_note(profile):
        return None
    return AvailabilityNote.objects.create(profile=profile, text=text, created_by=by)


def note_history(profile) -> list:
    """All notes for ``profile``, most recent first."""
    return list(profile.availability_notes.select_related("created_by"))


def interview_status_map(user_ids) -> dict[int, str]:
    """``{user_id: status}`` for the **Application Interviews** function, over the
    given users — the bridge the admissions flow uses to staff interviewers by
    availability. Users without an open span are simply absent (treat as
    Unknown). Empty if the function isn't configured."""
    fn = AnalystFunction.objects.filter(slug="application-interviews").first()
    if fn is None:
        return {}
    return dict(
        AvailabilitySpan.objects.filter(
            function=fn, end_date__isnull=True, profile__user_id__in=list(user_ids)
        ).values_list("profile__user_id", "status")
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


def _coverage_profile_ids() -> list[int]:
    """PKs of the analysts the coverage report counts — eligible, active, real."""
    return list(
        eligible_profiles()
        .filter(is_persona=False, user__is_active=True)
        .values_list("pk", flat=True)
    )


def current_coverage(*, as_of=None) -> list[dict]:
    """How many analysts are currently available (YES) for each active function.

    Returns ``[{function, yes, total, pct}, ...]`` — the school's present
    capacity in each area, for the coordinator's overview.
    """
    from collections import Counter

    functions = list(AnalystFunction.objects.filter(is_active=True))
    profs = _coverage_profile_ids()
    total = len(profs)
    counts = Counter(
        AvailabilitySpan.objects.filter(
            function__in=functions, status=Status.YES, end_date__isnull=True,
            profile_id__in=profs,
        ).values_list("function_id", flat=True)
    )
    return [
        {
            "function": f,
            "yes": counts.get(f.pk, 0),
            "total": total,
            "pct": round(counts.get(f.pk, 0) / total * 100) if total else 0,
        }
        for f in functions
    ]


def coverage_series(*, months: int = 12, as_of=None) -> dict:
    """Monthly count of analysts available (YES) per function over the last
    ``months`` months — the data for the historical coverage chart.

    Returns ``{"labels": [...], "datasets": [{"label", "data"}, ...]}`` shaped
    for Chart.js. A month's count is the analysts whose YES span covers that
    month's first day.
    """
    as_of = as_of or timezone.localdate()
    functions = list(AnalystFunction.objects.filter(is_active=True))
    profs = set(_coverage_profile_ids())

    dates = []
    base = as_of.year * 12 + (as_of.month - 1)
    for i in range(months - 1, -1, -1):
        yy, mm = divmod(base - i, 12)
        dates.append(_dt.date(yy, mm + 1, 1))

    yes_spans = [
        s for s in AvailabilitySpan.objects.filter(
            function__in=functions, status=Status.YES
        ).values("function_id", "profile_id", "start_date", "end_date")
        if s["profile_id"] in profs
    ]

    datasets = []
    for f in functions:
        spans_f = [s for s in yes_spans if s["function_id"] == f.pk]
        data = []
        for d in dates:
            data.append(sum(
                1 for s in spans_f
                if s["start_date"] <= d and (s["end_date"] is None or s["end_date"] > d)
            ))
        datasets.append({"label": f.column_label, "data": data})

    return {"labels": [d.strftime("%b %Y") for d in dates], "datasets": datasets}
