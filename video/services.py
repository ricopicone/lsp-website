"""Provisioning + access logic for Workgroup-anchored Daily rooms.

The room is created on first join and reused thereafter (one stable room per
group). Access reuses the workgroup's *existing* membership predicates rather
than inventing new rules:

* enter  -> ``Workgroup.is_member`` (faculty + current-term paid/comped
            registrants for seminars; stored roster for other kinds).
* owner  -> ``events.permissions.can_edit_event`` for the offering's event, or
            a stored lead role (chair / co-chair / faculty / organizer).
"""
from __future__ import annotations

import logging
import time

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied

from . import daily
from .models import DailyRoom

logger = logging.getLogger("video")

ROOM_PREFIX = "lsp-"

#: Live presence is fetched account-wide once and cached briefly — a single
#: ``GET /presence`` covers every room, and a ~20s staleness is fine for a
#: "someone's in the room" indicator. Daily's own data lags up to ~15s anyway.
PRESENCE_CACHE_KEY = "video:daily:presence"
PRESENCE_TTL_SECONDS = 20


def daily_enabled() -> bool:
    """True only when the feature flag and the credentials are all present."""
    return bool(
        settings.DAILY_ENABLED and settings.DAILY_API_KEY and settings.DAILY_DOMAIN
    )


def _is_workgroup(owner) -> bool:
    from workgroups.models import Workgroup

    return isinstance(owner, Workgroup)


def _room_name(owner) -> str:
    prefix = ROOM_PREFIX if _is_workgroup(owner) else f"{ROOM_PREFIX}ch-"
    return f"{prefix}{owner.slug}"[:128]


def ensure_room(owner) -> DailyRoom | None:
    """Return the owner's Daily room, creating it on the provider if needed.

    ``owner`` is a Workgroup or a Parlêtre Channel; both expose a ``video_room``
    reverse accessor. Idempotent. Returns ``None`` when the feature is disabled or
    provisioning fails — callers then fall back to ``access_info``.
    """
    if not daily_enabled():
        return None

    room = getattr(owner, "video_room", None)
    if room is not None and room.provider_created:
        return room

    name = room.name if room is not None else _room_name(owner)
    properties = {
        "enable_recording": False,  # case-history privacy — never enable
        "enable_prejoin_ui": True,
        "enable_knocking": False,  # token-gated, not knock-to-enter
    }
    if settings.DAILY_MAX_PARTICIPANTS:
        properties["max_participants"] = settings.DAILY_MAX_PARTICIPANTS

    try:
        data = daily.create_room(name, properties=properties)
    except daily.DailyError:
        logger.exception("Daily ensure_room failed for %s", _room_name(owner))
        return None

    url = data.get("url") or f"https://{settings.DAILY_DOMAIN}/{name}"
    if room is None:
        owner_kwarg = {"workgroup": owner} if _is_workgroup(owner) else {"channel": owner}
        room = DailyRoom.objects.create(
            name=name, url=url, provider_created=True, **owner_kwarg
        )
    else:
        room.url = url
        room.provider_created = True
        room.save(update_fields=["url", "provider_created", "last_synced_at"])
    return room


def mint_token(room: DailyRoom, user, *, is_owner: bool = False) -> str:
    """A short-lived meeting token for ``user`` to join ``room``."""
    exp = int(time.time()) + settings.DAILY_TOKEN_TTL_MINUTES * 60
    name = ""
    if user is not None:
        name = (getattr(user, "get_full_name", lambda: "")() or "").strip()
        name = name or getattr(user, "email", "") or ""
    return daily.create_meeting_token(
        room_name=room.name, user_name=name[:255], is_owner=is_owner, exp=exp
    )


def can_enter(workgroup, user) -> bool:
    """Whether ``user`` may join the workgroup's room (the access primitive)."""
    return workgroup.is_member(user)


def is_owner(workgroup, user) -> bool:
    """Whether ``user`` should join as a moderator (owner controls)."""
    event = workgroup.primary_event() or workgroup.current_term()
    if event is not None:
        from events.permissions import can_edit_event

        if can_edit_event(user, event):
            return True
    from workgroups.models import WorkgroupMembership

    return workgroup.memberships.serving().filter(
        user=user, role__in=WorkgroupMembership.LEAD_ROLES
    ).exists()


# ---- Live presence ------------------------------------------------------

def presence_map() -> dict:
    """``{room_name: [participant, ...]}`` for currently-occupied rooms, cached
    ~20s. Empty when the feature is off or the API call fails (never raises)."""
    if not daily_enabled():
        return {}
    cached = cache.get(PRESENCE_CACHE_KEY)
    if cached is not None:
        return cached
    try:
        data = daily.get_presence()
    except daily.DailyError:
        logger.warning("Daily presence fetch failed", exc_info=True)
        data = {}
    cache.set(PRESENCE_CACHE_KEY, data, PRESENCE_TTL_SECONDS)
    return data


def room_participant_count(room) -> int:
    """Live participant count for a ``DailyRoom`` (or None). 0 when the room is
    unprovisioned or empty — and skips the presence fetch entirely for None."""
    if room is None:
        return 0
    return len(presence_map().get(room.name, []))


def live_room_names() -> set[str]:
    """Names of rooms with at least one participant right now."""
    return {name for name, people in presence_map().items() if people}


# ---- Parlêtre channel rooms (board-level video channels) ----------------

def can_enter_channel(channel, user) -> bool:
    """Whether ``user`` may join a video channel's room — the channel's own
    visibility rule (Open / Role / Committee / Workgroup / Private / LSP Staff)."""
    from parletre.permissions import channel_visible

    return channel_visible(channel, user)


def is_channel_owner(channel, user) -> bool:
    """Moderator (Daily owner) for a channel room = the channel's moderators."""
    from parletre.permissions import channel_can_moderate

    return channel_can_moderate(channel, user)


def channel_room_context(request, channel) -> dict:
    """Room context for rendering a video channel (standalone page or inline).

    A workgroup-access channel reuses its workgroup's room; other channels anchor
    on the channel itself. Returns ``{room_url, room_token, is_owner}`` or
    ``{"room_unavailable": True}`` when Daily is off / provisioning fails.
    """
    user = request.user
    if not can_enter_channel(channel, user):
        raise PermissionDenied("You don't have access to this room.")
    owner = channel.workgroup or channel
    room = ensure_room(owner)
    if room is None:
        return {"room_unavailable": True}
    owner_flag = is_channel_owner(channel, user)
    try:
        token = mint_token(room, user, is_owner=owner_flag)
    except Exception:  # noqa: BLE001 — degrade to the unavailable state
        logger.exception("Daily token mint failed for channel %s", channel.slug)
        return {"room_unavailable": True}
    return {"room_url": room.url, "room_token": token, "is_owner": owner_flag}
