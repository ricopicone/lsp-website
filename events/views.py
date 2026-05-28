"""Public-facing event views (PROG-1, PROG-7, PROG-8)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import EventDescriptionForm, PricingCodeForm
from .models import Event, PricingCode
from .permissions import can_edit_event


def _faculty_view_url(event: Event) -> str:
    return reverse("events:detail", args=[event.slug]) + "?view=faculty"


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
    has_paid_registration = bool(
        user_registration and user_registration.status == Registration.Status.PAID
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
