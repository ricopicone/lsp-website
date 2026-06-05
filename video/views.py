"""Auth-gated embed views for Workgroup video rooms.

``/groups/<slug>/room/`` and ``/events/<slug>/room/`` both resolve to a single
Workgroup, check membership, ensure the Daily room exists, mint a per-user
token, and render the embedded Daily Prebuilt iframe. The raw Daily URL is
useless without a token, so emailing/linking these gated URLs is safe.
"""
from __future__ import annotations

import json
import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from events.models import Event
from workgroups.models import Workgroup

from . import daily, services
from .models import Recording

logger = logging.getLogger("video")


@login_required
def system_check(request):
    """Pre-event tech check — a throwaway Daily room that lands on the device /
    mic / camera / network prejoin screen and auto-closes ~10 min."""
    return render(request, "video/system_check.html", services.system_check_context(request))


@login_required
def workgroup_room(request, slug):
    wg = get_object_or_404(Workgroup, slug=slug)
    # Back to the Meet tab (where the join happened), not the default Overview.
    return _render_room(request, wg, back_url=f"{wg.get_absolute_url()}?tab=meet")


@login_required
def event_room(request, slug):
    event = get_object_or_404(Event, slug=slug)
    wg = event.workgroup or event.ensure_workgroup()
    if wg is None:
        raise Http404("This event has no meeting room.")
    return _render_room(
        request, wg, event=event, back_url=reverse("events:detail", args=[event.slug])
    )


@login_required
def recording_play(request, pk):
    """Watch (or ?download=1) a recording, gated by its content visibility."""
    rec = get_object_or_404(Recording, pk=pk)
    if not rec.content_visible_to(request.user):
        raise PermissionDenied("You don't have access to this recording.")
    download = bool(request.GET.get("download"))
    url = rec.playable_url(download=download)
    if url is None:
        return render(request, "video/recording_unavailable.html", {"recording": rec})
    if download:
        return HttpResponseRedirect(url)
    back = ""
    if rec.event_id:
        back = reverse("events:detail", args=[rec.event.slug])
    elif rec.room and rec.room.workgroup_id:
        back = rec.room.workgroup.get_absolute_url()
    from datetime import timedelta

    from django.conf import settings

    expires_on = rec.created_at + timedelta(
        days=getattr(settings, "RECORDING_RETENTION_DAYS", 365)
    )
    return render(
        request, "video/recording_play.html",
        {
            "recording": rec, "play_url": url, "back_url": back,
            "can_manage": rec.can_manage(request.user),
            "expires_on": expires_on,
        },
    )


@login_required
@require_POST
def recording_keep(request, pk):
    """Toggle a recording's keep flag (host/staff) — kept recordings are exempt
    from the 1-year retention sweep."""
    rec = get_object_or_404(Recording, pk=pk)
    if not rec.can_manage(request.user):
        raise PermissionDenied("You can't manage this recording.")
    rec.keep = not rec.keep
    rec.save(update_fields=["keep"])
    return HttpResponseRedirect(reverse("video:recording_play", args=[rec.pk]))


@csrf_exempt
@require_POST
def recording_webhook(request):
    """Daily recording lifecycle webhook (recording.started / ready-to-download /
    error). Signature-verified; idempotent on the Daily recording id."""
    timestamp = request.META.get("HTTP_X_WEBHOOK_TIMESTAMP", "")
    signature = request.META.get("HTTP_X_WEBHOOK_SIGNATURE", "")
    raw = request.body
    # Daily's registration handshake POSTs an unsigned liveness ping — just 200 it
    # (there's no data to trust). Anything carrying a signature must verify.
    if not signature:
        return HttpResponse(status=200)
    if not daily.verify_webhook(timestamp, raw, signature):
        logger.warning("Daily webhook rejected: bad signature")
        return HttpResponseBadRequest("invalid signature")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return HttpResponseBadRequest("invalid JSON")

    event_type = body.get("type") or body.get("event_type") or ""
    payload = body.get("payload") or body
    if event_type.startswith("recording."):
        try:
            services.ingest_recording_event(event_type, payload)
        except Exception:
            logger.exception("Daily recording webhook handler failed (%s)", event_type)
            return HttpResponse("internal error", status=500)
    return HttpResponse(status=200)


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
            # Owner's browser auto-starts recording for flagged events.
            "auto_record": bool(owner and event is not None and event.record_video),
        },
    )
