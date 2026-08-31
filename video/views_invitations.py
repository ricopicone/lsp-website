"""Inviting someone into a group's meeting room, and letting them in (task #694).

Owns everything an invitation touches that is not specific to a personal room:
the guest doorstep (which serves every target), the two presence endpoints a
waiting doorstep polls, the per-target invite POST, and one revoke endpoint
shared by all three targets.

The guest route and its URL name are unchanged from #687 — links have been
mailed — so this module took the view over rather than adding a second one.
"""
from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from events.models import Event
from workgroups.models import Workgroup

from . import invitations as inv
from . import services
from .forms_invitations import GuestJoinForm, InvitationForm
from .models import RoomInvitation

logger = logging.getLogger("video")


# ---- joining ------------------------------------------------------------

def guest_room(request, token):
    """The guest doorstep for any target, and the join it POSTs to.

    GET renders and mints nothing. Email link-scanners pre-click links on exactly
    the addresses this gets mailed to (``auth-email-scanner-and-reset-gotchas``),
    and while an invitation is deliberately not single-use, a GET that minted a
    Daily token would put a scanner in the room.
    """
    invitation = inv.guest_invitation(token)
    if invitation is None:
        return render(request, "video/invite/invalid.html", status=404)
    target = inv.target_of(invitation)
    if target.is_personal:
        # #687's doorstep, whose refusal copy names the host and whose rule is
        # the stricter one (the owner specifically must be present).
        from .views_personal import personal_guest_room

        return personal_guest_room(request, invitation)

    form = GuestJoinForm(
        request.POST or None, initial={"display_name": invitation.guest_name}
    )
    if request.method != "POST" or not form.is_valid():
        return _doorstep(request, invitation, target, form)
    try:
        inv.check_entry(target, request.user, invitation=invitation)
    except inv.EntryRefused:
        return _doorstep(request, invitation, target, form)
    invitation.touch()
    return _join_as_guest(request, target, form.cleaned_data["display_name"])


def guest_presence(request, token):
    """``{"live": bool}`` for a waiting guest doorstep.

    Answered to the *invitation*, not to the room: only someone holding one may
    ask whether a group's meeting has started, so knowing a workgroup slug does
    not let anyone probe a committee's live state. It names nobody and counts
    nobody.
    """
    invitation = inv.guest_invitation(token)
    if invitation is None:
        raise Http404
    return JsonResponse({"live": inv.target_of(invitation).someone_present()})


@login_required
def invitation_presence(request, pk):
    """The same, for a signed-in invitee waiting at the room's own URL."""
    invitation = get_object_or_404(RoomInvitation, pk=pk, invited_user=request.user)
    if not invitation.is_live:
        raise Http404
    return JsonResponse({"live": inv.target_of(invitation).someone_present()})


def _join_as_guest(request, target, guest_name: str):
    room = services.ensure_room(target.owner)
    if room is None:
        return render(request, "video/room_unavailable.html", {
            "workgroup": None, "event": None, "back_url": "/",
        })
    event = target.owner if isinstance(target, inv.EventTarget) else None
    # A guest at a spotlight event joins muted and camera-off like every other
    # attendee, and their token covers the event's joinable window rather than
    # the flat TTL.
    off = services.spotlight_start_off(target.owner, False)
    try:
        token = inv.guest_token(
            room, guest_name, exp=services.token_exp_for(event),
            start_audio_off=off, start_video_off=off,
        )
    except Exception:  # noqa: BLE001 — degrade to the unavailable page
        logger.exception("Daily token mint failed for guest in %s", room.name)
        return render(request, "video/room_unavailable.html", {
            "workgroup": None, "event": None, "back_url": "/",
        })
    return render(request, "video/room.html", {
        # Both are title-only in the template; a guest's page names the room they
        # were invited into, the same as a member's does.
        "workgroup": target.owner if isinstance(target, inv.WorkgroupTarget) else None,
        "event": event,
        "room_url": room.url,
        "token": token,
        "is_owner": False,
        "back_url": "",
        "recording_available": getattr(target.owner, "recording_mode", "on_demand") != "off",
        "auto_record": False,
    })


def _doorstep(request, invitation, target, form=None, *, back_url=""):
    return render(request, "video/invite/doorstep.html", {
        "invitation": invitation,
        "target_label": target.label,
        "inviter": _inviter_name(invitation),
        "live": target.someone_present(),
        "form": form,
        "poll_url": _poll_url(invitation),
        "back_url": back_url,
    })


def _inviter_name(invitation) -> str:
    by = invitation.invited_by
    if by is None:
        return ""
    return by.get_full_name() or ""


def _poll_url(invitation) -> str:
    from django.urls import reverse

    if invitation.is_guest:
        return reverse("video:guest_presence", args=[invitation.token])
    return reverse("video:invitation_presence", args=[invitation.pk])


def doorstep_for_invitee(request, invitation, target, *, back_url=""):
    """The waiting page a signed-in invitee sees at the room's own URL."""
    return _doorstep(request, invitation, target, back_url=back_url)


# ---- managing -----------------------------------------------------------

@login_required
@require_POST
def workgroup_invite(request, slug):
    wg = get_object_or_404(Workgroup, slug=slug)
    return _invite(request, inv.target_for(wg))


@login_required
@require_POST
def event_invite(request, slug):
    event = get_object_or_404(Event, slug=slug)
    target = inv.target_for_event(event, create=True)
    if not isinstance(target, inv.EventTarget):
        # An offering meets in its workgroup's room; it is invited to from the
        # Workspace, and minting an event-target invitation here would bind it to
        # a room the event does not own.
        raise Http404("This event has no room of its own.")
    return _invite(request, target)


@login_required
@require_POST
def invitation_revoke(request, pk):
    """One endpoint for all three targets; ``may_invite`` is what differs, and a
    personal room's is still its own member alone.

    Refuses with 404 rather than 403, which is what the personal-room endpoint
    this replaces did: a stranger should not have it confirmed that invitation
    *n* exists.
    """
    invitation = get_object_or_404(RoomInvitation, pk=pk)
    target = inv.target_of(invitation)
    if not target.may_invite(request.user):
        raise Http404
    invitation.revoke()
    messages.success(request, f"{invitation.display_name}'s invitation was revoked.")
    return redirect(target.back_url())


def _invite(request, target):
    if not target.may_invite(request.user):
        raise PermissionDenied("You can't invite people into this meeting room.")
    from . import notifications_invitations as notify_room

    form = InvitationForm(request.POST, target=target)
    if not form.is_valid():
        for error in form.errors.values():
            messages.error(request, error[0])
        return redirect(target.back_url())

    send_email = form.cleaned_data.get("send_email")
    invited, already = [], []
    for recipient in form.cleaned_data["recipients"]:
        if form.already_invited(recipient):
            already.append(recipient.label)
            continue
        invitation = form.build(recipient, by=request.user)
        # An account holder is always told; a guest link is mailed only when an
        # address was given and the lead asked us to send it.
        if send_email or not invitation.is_guest:
            notify_room.send_invitation(invitation)
        invited.append(invitation)

    if invited:
        messages.success(
            request,
            f"{_and_list([i.display_name for i in invited])} invited to "
            f"{target.label}'s meeting room.",
        )
        guests = [i.display_name for i in invited if i.is_guest]
        if guests:
            noun = "link" if len(guests) == 1 else "links"
            messages.info(request, f"Copy the {noun} below to send to {_and_list(guests)}.")
    if already:
        messages.info(
            request,
            f"{_and_list(already)} already had a live invitation, so nothing changed.",
        )
    return redirect(target.back_url())


def _and_list(names) -> str:
    """"a", "a and b", "a, b and c" — the message names everyone it acted on."""
    names = list(names)
    if len(names) <= 1:
        return names[0] if names else ""
    return f"{', '.join(names[:-1])} and {names[-1]}"
