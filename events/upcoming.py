"""Selection of the landing page's "Coming up" list (task #461).

The annual program's seminars all begin within days of each other in September,
so a one-off special event scheduled in the same stretch gets pushed off a
four-item chronological list by events that aren't time-critical — a seminar's
start date is the least interesting thing about it, while a special event *is*
its date. So the list reserves up to two slots at the top for standalone-type
events starting soon, a true Special event first.

Design: docs/superpowers/specs/2026-07-23-pinned-special-events-design.md
"""

from __future__ import annotations

from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.db import models
from django.utils import timezone

from accounts.permissions import is_lsp_member

from .models import Event

#: How far ahead a standalone event may start and still be pinned.
PIN_WINDOW_MONTHS = 2
#: Ceiling on pinned rows, so the chronological list is never crowded out.
MAX_PINNED = 2
#: A year-long seminar that began this recently still shows, so late
#: registration stays reachable from the front page.
LATE_SEMINAR_GRACE_DAYS = 31

_SEMINAR_TYPES = (Event.Type.SEMINAR, Event.Type.SCHOLARLY_SEMINAR)


def _base_queryset(user, today):
    """Published events that haven't started yet — plus seminars inside the
    late-registration grace — narrowed to what ``user`` may see."""
    grace_start = today - timedelta(days=LATE_SEMINAR_GRACE_DAYS)
    qs = Event.objects.filter(published=True).filter(
        models.Q(start_date__gte=today)
        | models.Q(
            event_type__in=_SEMINAR_TYPES,
            start_date__gte=grace_start,
            start_date__lt=today,
            end_date__gte=today,
        )
    )
    if not is_lsp_member(user):
        qs = qs.filter(visibility=Event.Visibility.PUBLIC)
    return qs.order_by("start_date", "title")


def landing_events(user, limit: int = 4) -> list[Event]:
    """The "Coming up" list: up to ``MAX_PINNED`` soon standalone events first,
    then the chronological remainder, ``limit`` items in all.

    Pinned instances carry a transient ``pinned`` attribute the template uses to
    tint their type badge, so a later date sitting above an earlier one reads as
    deliberate rather than broken.
    """
    today = timezone.now().date()
    base = _base_queryset(user, today)

    pinned = list(
        base.exclude(event_type__in=Event.ANNUAL_PROGRAM_TYPES)
        .filter(start_date__lte=today + relativedelta(months=PIN_WINDOW_MONTHS))
        .annotate(
            _not_special=models.Case(
                models.When(event_type=Event.Type.SPECIAL_EVENT, then=0),
                default=1,
                output_field=models.IntegerField(),
            )
        )
        .order_by("_not_special", "start_date", "title")[:MAX_PINNED]
    )
    for event in pinned:
        event.pinned = True

    # The pins can't be found by slicing the chronological list first — being
    # outside the top few is the condition this feature exists to fix.
    rest = base.exclude(pk__in=[e.pk for e in pinned])[: max(0, limit - len(pinned))]
    return pinned + list(rest)
