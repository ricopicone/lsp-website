"""Landing page and unified calendar (PROG-1, PROG-6)."""

from __future__ import annotations

from datetime import datetime

from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from events.models import Event, Session


def landing(request):
    """Public landing page for app.lacanschool.org."""
    today = timezone.now().date()
    upcoming = (
        Event.objects.filter(published=True, end_date__gte=today)
        .order_by("start_date", "title")[:5]
    )
    user_registrations_url = None
    dues_period_unpaid = None
    if request.user.is_authenticated:
        from payments.dues import is_dues_obligated, user_paid_for_period
        from payments.models import DuesPeriod
        from registrations.models import Registration

        latest = (
            Registration.objects.filter(user=request.user)
            .exclude(status__in=(
                Registration.Status.CANCELLED,
                Registration.Status.REFUNDED,
            ))
            .order_by("-created_at")
            .first()
        )
        if latest is not None:
            user_registrations_url = reverse(
                "registrations:confirm", args=[latest.id]
            )

        # Dues banner for obligated unpaid members.
        current_period = DuesPeriod.current()
        if (
            current_period is not None
            and is_dues_obligated(request.user)
            and not user_paid_for_period(request.user, current_period)
        ):
            dues_period_unpaid = current_period

    return render(
        request,
        "core/landing.html",
        {
            "upcoming_events": upcoming,
            "user_registrations_url": user_registrations_url,
            "dues_period_unpaid": dues_period_unpaid,
        },
    )


def _is_staff(user):
    return user.is_authenticated and user.is_staff


def calendar_page(request):
    """Render the month-grid calendar shell.

    Public for everyone; the JSON feed filters by published status for
    non-staff users so drafts only appear to admins.
    """
    return render(request, "core/calendar.html")


def calendar_events_json(request):
    """JSON feed for FullCalendar.

    Accepts ``start`` / ``end`` query params (FullCalendar sends them
    automatically per view). Non-staff users only see Sessions for
    published events; staff see everything (including drafts).
    """
    start_param = request.GET.get("start")
    end_param = request.GET.get("end")

    qs = Session.objects.select_related("event")
    if not _is_staff(request.user):
        qs = qs.filter(event__published=True)

    start = _parse(start_param) if start_param else None
    end = _parse(end_param) if end_param else None
    if start:
        qs = qs.filter(end_at__gte=start)
    if end:
        qs = qs.filter(start_at__lte=end)

    payload = [
        {
            "id": s.id,
            "title": s.title or s.event.title,
            "start": s.start_at.isoformat(),
            "end": s.end_at.isoformat(),
            "url": (
                reverse("admin:events_event_change", args=[s.event_id])
                if _is_staff(request.user)
                else reverse("events:detail", args=[s.event.slug])
            ),
            "extendedProps": {
                "event": s.event.title,
                "location": s.location,
                "sequence": s.sequence,
            },
        }
        for s in qs
    ]
    return JsonResponse(payload, safe=False)


def _parse(value: str) -> datetime | None:
    """Accept ISO datetime *or* a bare date (FullCalendar sends both).

    Always returns a timezone-aware datetime in the project's current TZ;
    Django warns on naive datetime queries against ``DateTimeField``.
    """
    dt = parse_datetime(value)  # Django ≥4 accepts bare dates here (returns naive).
    if dt is None:
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt
