"""Auth-gated embed views for Workgroup video rooms.

``/groups/<slug>/room/`` and ``/events/<slug>/room/`` both resolve to a single
Workgroup, check membership, ensure the Daily room exists, mint a per-user
token, and render the embedded Daily Prebuilt iframe. The raw Daily URL is
useless without a token, so emailing/linking these gated URLs is safe.
"""
from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from events.models import Event
from workgroups.models import Workgroup

from . import services

logger = logging.getLogger("video")


@login_required
def system_check(request):
    """Pre-event tech check — a throwaway Daily room that lands on the device /
    mic / camera / network prejoin screen and auto-closes ~10 min."""
    return render(request, "video/system_check.html", services.system_check_context(request))


@login_required
def workgroup_room(request, slug):
    wg = get_object_or_404(Workgroup, slug=slug)
    return _render_room(request, wg, back_url=wg.get_absolute_url())


@login_required
def event_room(request, slug):
    event = get_object_or_404(Event, slug=slug)
    wg = event.workgroup or event.ensure_workgroup()
    if wg is None:
        raise Http404("This event has no meeting room.")
    return _render_room(
        request, wg, event=event, back_url=reverse("events:detail", args=[event.slug])
    )


def _render_room(request, wg, *, event=None, back_url="/"):
    if not services.can_enter(wg, request.user):
        raise PermissionDenied("You don't have access to this meeting room.")

    room = services.ensure_room(wg)
    if room is None:
        return render(
            request,
            "video/room_unavailable.html",
            {"workgroup": wg, "event": event, "back_url": back_url},
        )

    owner = services.is_owner(wg, request.user)
    try:
        token = services.mint_token(room, request.user, is_owner=owner)
    except Exception:  # noqa: BLE001 — degrade to the fallback page
        logger.exception("Daily token mint failed for %s", wg.slug)
        return render(
            request,
            "video/room_unavailable.html",
            {"workgroup": wg, "event": event, "back_url": back_url},
        )

    return render(
        request,
        "video/room.html",
        {
            "workgroup": wg,
            "event": event,
            "room_url": room.url,
            "token": token,
            "is_owner": owner,
            "back_url": back_url,
        },
    )
