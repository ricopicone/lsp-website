"""A member's private meeting room: joining it, and letting others in (task #687).

Four entrances, all of which go through
``services_personal.check_entry`` and so all of which hold the same invariant —
nobody but the owner is in the room unless the owner is in it:

* ``my_room``       the member's own room;
* ``personal_room`` an invited account holder, or a member during posted hours;
* ``guest_room``    an anonymous guest holding a secret link;
* ``room_presence`` the tiny JSON the doorstep polls while it waits.

The management endpoints (settings, invite, revoke) live here too rather than in
``formation``, so everything that can change a room's access sits in one file.
"""
from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import services_personal as personal
from .forms_personal import GuestJoinForm, InvitationForm, PersonalRoomSettingsForm
from .models import PersonalRoom, RoomInvitation

logger = logging.getLogger("video")

def _hub_url() -> str:
    """Where the member manages their room: the My LSP hub tab, so the avatar
    menu picks it up for free from ``my_lsp_tabs``."""
    return f"{reverse('formation:formation')}?tab=room"


def _use_policy() -> str:
    """One sentence, in the member-facing register (commas, not em dashes)."""
    return (
        "This room is for the work of the School, for example office hours, "
        "interviews, and committee conversations. Please do not use it for "
        "clinical work with analysands."
    )


# ---- joining ------------------------------------------------------------

@login_required
def my_room(request):
    """The member's own room. Creates it on first visit."""
    room = personal.personal_room_for(request.user, create=True)
    if room is None:
        raise Http404("Private meeting rooms are for members of the School.")
    context = personal.room_context(request, room, is_owner=True)
    return _render_personal(request, room, context, back_url=_hub_url())


@login_required
def personal_room(request, slug):
    """An invited account holder, or an LSP member during posted office hours."""
    room = get_object_or_404(PersonalRoom.objects.select_related("user"), slug=slug)
    if request.user.pk == room.user_id:
        return redirect("video:my_room")

    invitation = personal.invitation_for(room, request.user)
    try:
        # Hand the invitation over rather than letting check_entry re-query it;
        # it re-validates liveness either way (_invitation_admits).
        personal.check_entry(room, request.user, invitation=invitation)
    except personal.EntryRefused as refused:
        return _refused(request, room, refused, poll_url=_presence_url(room))

    personal.touch_invitation(invitation)
    context = personal.room_context(request, room, is_owner=False)
    return _render_personal(request, room, context, back_url="/")


def guest_room(request, token):
    """The guest doorstep, and the join it POSTs to.

    GET renders and mints nothing. Email link-scanners pre-click links on
    exactly the addresses this gets mailed to
    (``auth-email-scanner-and-reset-gotchas``), and while the invitation is
    deliberately not single-use, a GET that minted a Daily token would put a
    scanner in the room.
    """
    invitation = personal.guest_invitation(token)
    if invitation is None:
        return render(request, "video/personal/guest_invalid.html", status=404)
    room = invitation.room

    if request.method != "POST":
        return _doorstep(request, invitation, GuestJoinForm(
            initial={"display_name": invitation.guest_name},
        ))

    form = GuestJoinForm(request.POST)
    if not form.is_valid():
        return _doorstep(request, invitation, form)
    try:
        personal.check_entry(room, request.user, invitation=invitation)
    except personal.EntryRefused as refused:
        return _doorstep(request, invitation, form, refused=refused)

    personal.touch_invitation(invitation)
    context = personal.room_context(
        request, room, is_owner=False,
        guest_name=form.cleaned_data["display_name"],
    )
    return _render_personal(request, room, context, back_url="")


def room_presence(request, slug):
    """``{"live": bool}`` — polled by a waiting doorstep.

    Says only whether the host is in the room, and only for a room whose slug
    the caller already holds; it names nobody and counts nobody.
    """
    room = PersonalRoom.objects.filter(slug=slug).first()
    if room is None:
        raise Http404
    return JsonResponse({"live": personal.owner_present(room)})


# ---- managing -----------------------------------------------------------

@login_required
@require_POST
def room_settings(request):
    room = personal.personal_room_for(request.user, create=True)
    if room is None:
        raise Http404("Private meeting rooms are for members of the School.")
    form = PersonalRoomSettingsForm(request.POST, instance=room)
    if form.is_valid():
        form.save()
        messages.success(request, "Your meeting room settings were saved.")
    else:
        for error in form.errors.values():
            messages.error(request, error[0])
    return redirect(_hub_url())


@login_required
@require_POST
def room_invite(request):
    room = personal.personal_room_for(request.user, create=True)
    if room is None:
        raise Http404("Private meeting rooms are for members of the School.")
    form = InvitationForm(request.POST, room=room)
    if not form.is_valid():
        for error in form.errors.values():
            messages.error(request, error[0])
        return redirect(_hub_url())

    from . import notifications_personal as notify_room

    send_email = form.cleaned_data.get("send_email")
    invited, already = [], []
    for recipient in form.cleaned_data["recipients"]:
        if form.already_invited(recipient):
            already.append(recipient.label)
            continue
        invitation = form.build(recipient)
        # An account holder is always told; a guest link is mailed only when the
        # member gave an address and asked us to send it.
        if send_email or not invitation.is_guest:
            notify_room.send_invitation(invitation)
        invited.append(invitation)

    if invited:
        messages.success(
            request,
            f"{_and_list([i.display_name for i in invited])} invited to your room.",
        )
        # Only a guest has a link to hand over, so name them rather than telling
        # someone to copy a link for a member who signs in as themselves.
        guests = [i.display_name for i in invited if i.is_guest]
        if guests:
            noun = "link" if len(guests) == 1 else "links"
            messages.info(
                request, f"Copy the {noun} below to send to {_and_list(guests)}."
            )
    if already:
        messages.info(
            request,
            f"{_and_list(already)} already had a live invitation, so nothing changed.",
        )
    return redirect(_hub_url())


def _and_list(names) -> str:
    """"a", "a and b", "a, b and c" — the message names everyone it acted on."""
    names = list(names)
    if len(names) <= 1:
        return names[0] if names else ""
    return f"{', '.join(names[:-1])} and {names[-1]}"


@login_required
@require_POST
def room_invite_revoke(request, pk):
    invitation = get_object_or_404(RoomInvitation, pk=pk, room__user=request.user)
    invitation.revoke()
    messages.success(request, f"{invitation.display_name}'s invitation was revoked.")
    return redirect(_hub_url())


# ---- rendering ----------------------------------------------------------

def _presence_url(room) -> str:
    return reverse("video:room_presence", args=[room.slug])


def _render_personal(request, room, context, *, back_url=""):
    if context.get("room_unavailable"):
        return render(request, "video/room_unavailable.html", {
            "workgroup": None, "event": None, "back_url": back_url or "/",
        })
    context = {
        **context,
        "back_url": back_url,
        "auto_record": False,
        "room_title": f"{personal.owner_display(room)} — private meeting room",
        "personal_use_policy": _use_policy(),
    }
    return render(request, "video/personal/room.html", context)


def _refused(request, room, refused, *, poll_url=""):
    """The doorstep for a signed-in visitor who cannot come in yet."""
    return render(
        request, "video/personal/waiting.html",
        {
            "room": room, "host": personal.owner_display(room),
            "refused": refused, "poll_url": poll_url if refused.waiting else "",
            "use_policy": _use_policy(),
        },
        status=200 if refused.waiting else 403,
    )


def _doorstep(request, invitation, form, *, refused=None):
    room = invitation.room
    live = personal.owner_present(room)
    return render(
        request, "video/personal/guest_doorstep.html",
        {
            "invitation": invitation, "room": room, "form": form,
            "host": personal.owner_display(room), "live": live,
            "refused": refused, "poll_url": _presence_url(room),
            "use_policy": _use_policy(),
        },
    )
