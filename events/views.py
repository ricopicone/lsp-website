"""Public-facing event views (PROG-1)."""

from __future__ import annotations

from django.http import Http404
from django.shortcuts import get_object_or_404, render

from .models import Event


def event_detail(request, slug: str):
    """Render the public event page for a published event.

    Unpublished events 404 for anonymous and non-staff users; staff see them
    so they can preview before flipping ``published``.
    """
    event = get_object_or_404(
        Event.objects.prefetch_related("faculty", "sessions", "price_tiers"),
        slug=slug,
    )
    if not event.published and not (request.user.is_authenticated and request.user.is_staff):
        raise Http404("Event not found.")

    return render(
        request,
        "events/event_detail.html",
        {
            "event": event,
            "sessions": event.sessions.order_by("start_at"),
            "price_tiers": event.price_tiers.select_related("session").order_by(
                "session", "audience"
            ),
        },
    )
