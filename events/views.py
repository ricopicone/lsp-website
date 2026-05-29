"""Public-facing event views (PROG-1, PROG-7, PROG-8, REG-10)."""

from __future__ import annotations

import csv

from django.contrib.auth.decorators import login_required
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseForbidden,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import EventDescriptionForm, PricingCodeForm
from .models import (
    Event,
    PricingCode,
    academic_year_date_range,
    current_academic_year,
)
from .permissions import can_edit_event


def _faculty_view_url(event: Event) -> str:
    return reverse("events:detail", args=[event.slug]) + "?view=faculty"


def event_list(request):
    """Public chronological list of upcoming standalone events (PROG-1).

    Excludes annual-program types (seminars, reading groups, cartels) —
    those have a dedicated home at /program/. Members-only events are
    hidden from anonymous visitors.
    """
    today = timezone.now().date()
    events = (
        Event.objects.filter(published=True, end_date__gte=today)
        .exclude(event_type__in=Event.ANNUAL_PROGRAM_TYPES)
        .order_by("start_date", "title")
        .prefetch_related("faculty")
    )
    if not request.user.is_authenticated:
        events = events.filter(visibility=Event.Visibility.PUBLIC)
    return render(request, "events/event_list.html", {"events": events})


def program(request):
    """Annual program: seminars + other offerings for an academic year (PROG-2)."""
    year = request.GET.get("year") or current_academic_year()
    try:
        start, end = academic_year_date_range(year)
    except (ValueError, IndexError):
        raise Http404("Unknown academic year") from None

    base_qs = (
        Event.objects.filter(
            published=True, start_date__gte=start, start_date__lt=end,
        )
        .order_by("start_date", "title")
        .prefetch_related("faculty")
    )
    seminars = list(base_qs.filter(event_type=Event.Type.SEMINAR))
    offerings = list(base_qs.filter(
        event_type__in=[Event.Type.READING_GROUP, Event.Type.CARTEL]
    ))

    # Year-picker options: every distinct academic year that has at least
    # one published event (so the dropdown is data-driven, not hardcoded).
    distinct_years = sorted({
        e.academic_year
        for e in Event.objects.filter(published=True).only("start_date")
    }, reverse=True)
    current = current_academic_year()
    if current not in distinct_years:
        distinct_years.insert(0, current)

    return render(request, "events/program.html", {
        "year":            year,
        "seminars":        seminars,
        "offerings":       offerings,
        "available_years": distinct_years,
        "is_current_year": year == current,
    })


def event_detail(request, slug: str):
    """Render the public event page for a published event (PROG-1).

    Unpublished events 404 for anonymous and non-staff users; staff and
    faculty-editors see them so they can preview before flipping
    ``published``. If the current user has a *paid* Registration for the
    event, the page additionally shows the ``access_info`` block (REG-8).
    """
    from registrations.models import Registration

    event = get_object_or_404(
        Event.objects.prefetch_related("faculty", "sessions", "price_tiers"),
        slug=slug,
    )
    can_edit = can_edit_event(request.user, event)
    if not event.published and not can_edit:
        raise Http404("Event not found.")

    show_faculty_view = (
        can_edit and request.GET.get("view") == "faculty"
    )

    user_registration = None
    if request.user.is_authenticated:
        user_registration = (
            Registration.objects.filter(user=request.user, event=event)
            .exclude(status__in=(
                Registration.Status.CANCELLED,
                Registration.Status.REFUNDED,
            ))
            .order_by("-created_at")
            .first()
        )
    # PAID and COMPED both grant access — comp means the fee was waived,
    # not that they're excluded.
    has_paid_registration = bool(
        user_registration
        and user_registration.status in (
            Registration.Status.PAID,
            Registration.Status.COMPED,
        )
    )

    context = {
        "event": event,
        "sessions": event.sessions.order_by("start_at"),
        "price_tiers": event.price_tiers.select_related("session").order_by(
            "session", "audience"
        ),
        "can_edit": can_edit,
        "show_faculty_view": show_faculty_view,
        "user_registration": user_registration,
        "has_paid_registration": has_paid_registration,
    }
    if show_faculty_view:
        context["registrations"] = event.registrations.select_related(
            "user", "price_tier"
        ).order_by("created_at")
        context["pricing_code_form"] = PricingCodeForm()
        context["existing_codes"] = event.pricing_codes.order_by("-created_at")

    return render(request, "events/event_detail.html", context)


@login_required
def event_edit(request, slug: str):
    """Faculty-facing edit form for the event description (PROG-7)."""
    event = get_object_or_404(Event, slug=slug)
    if not can_edit_event(request.user, event):
        return HttpResponseForbidden(
            "You don't have permission to edit this event."
        )

    if request.method == "POST":
        form = EventDescriptionForm(request.POST, instance=event)
        if form.is_valid():
            form.save()
            return redirect("events:detail", slug=event.slug)
    else:
        form = EventDescriptionForm(instance=event)

    return render(request, "events/event_edit.html", {"event": event, "form": form})


@login_required
def check_pricing_code(request, slug: str):
    """JSON: look up a pricing code for this event and return its mode + value.

    Used by the register page to adapt the UI (slider vs fixed display) before
    submit. Returns ``ok=False`` for missing / invalid / unredeemable codes
    rather than HTTP errors — the front-end shows the message inline.
    """
    event = get_object_or_404(Event, slug=slug)
    raw = (request.GET.get("code") or "").strip().upper()
    if not raw:
        return JsonResponse({"ok": False, "error": "Empty code."})
    try:
        code = PricingCode.objects.get(code=raw, event=event)
    except PricingCode.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Code not recognized for this event."})
    if not code.is_redeemable(user=request.user):
        return JsonResponse({"ok": False, "error": "Code is not redeemable for you right now."})
    return JsonResponse({
        "ok": True,
        "mode": code.pricing_mode,
        "value": str(code.amount_or_percent),
    })


@login_required
def event_roster_csv(request, slug: str):
    """CSV export of an event's roster (REG-10).

    Active registrations only (awaiting_payment, paid, comped); cancelled
    and refunded rows are excluded. Permission mirrors event editing: event
    faculty, Programming Committee, LSP Staff, or Django is_staff.
    """
    from registrations.models import Registration

    event = get_object_or_404(Event, slug=slug)
    if not can_edit_event(request.user, event):
        return HttpResponseForbidden("You don't have permission to view this roster.")

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="{event.slug}-roster.csv"'
    )

    writer = csv.writer(response)
    writer.writerow([
        "first_name", "last_name", "email", "role",
        "tier", "amount", "status", "pricing_code", "registered_at",
    ])

    qs = (
        Registration.objects.filter(event=event)
        .exclude(status__in=(
            Registration.Status.CANCELLED,
            Registration.Status.REFUNDED,
        ))
        .select_related("user", "user__profile", "price_tier", "pricing_code")
        .order_by("created_at")
    )
    for r in qs:
        writer.writerow([
            r.user.first_name,
            r.user.last_name,
            r.user.email,
            getattr(getattr(r.user, "profile", None), "role", ""),
            r.price_tier.get_audience_display(),
            r.quoted_amount,
            r.get_status_display(),
            r.pricing_code.code if r.pricing_code else "",
            r.created_at.isoformat(),
        ])
    return response


@login_required
def event_generate_code(request, slug: str):
    """Mint a pricing code for the event (PROG-8 / REG-17).

    Permission is the same as event editing. On success, redirects back to
    the faculty view of the event detail page where the new code is listed.
    """
    event = get_object_or_404(Event, slug=slug)
    if not can_edit_event(request.user, event):
        return HttpResponseForbidden(
            "You don't have permission to issue codes for this event."
        )
    if request.method != "POST":
        return redirect(_faculty_view_url(event))

    form = PricingCodeForm(request.POST)
    if form.is_valid():
        code = form.save(commit=False)
        code.event = event
        code.issued_by = request.user
        code.save()

    return redirect(_faculty_view_url(event))
