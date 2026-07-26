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
import uuid

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


def _is_event(owner) -> bool:
    from events.models import Event

    return isinstance(owner, Event)


def _room_name(owner) -> str:
    if _is_workgroup(owner):
        prefix = ROOM_PREFIX
    elif _is_event(owner):
        prefix = f"{ROOM_PREFIX}event-"
    else:
        prefix = f"{ROOM_PREFIX}ch-"
    return f"{prefix}{owner.slug}"[:128]


#: Values Daily may hand back for a property we set to False. It stores a falsy
#: ``enable_recording`` as the string ``"0"``, so a raw ``==`` comparison would
#: see permanent drift and rewrite the room on every join.
_FALSEY = (False, 0, "0", "false", "", None)


def _norm(value):
    """Normalize a Daily room-config value so it compares equal to what we sent."""
    if value in _FALSEY:
        return False
    if value is True or value == "true":
        return True
    return value


def _desired_properties(owner) -> dict:
    """The room config ``owner`` should have. Single source of truth: ``ensure_room``
    applies it, and ``event_video_preflight`` checks the live room against it."""
    # Recording availability is per-owner (Workgroup/Channel/Event recording_mode);
    # "cloud" = hosts get a Record button (off until started), False = no button.
    recording = (
        "cloud" if getattr(owner, "recording_mode", "on_demand") != "off" else False
    )
    props = {
        "enable_recording": recording,
        "enable_prejoin_ui": True,   # device/mic/camera check before joining
        "enable_knocking": False,    # token-gated, not knock-to-enter
        "enable_chat": True,         # everyone can use text chat
        "enable_people_ui": True,    # participants panel + host mute/remove
        "enable_hand_raising": True,     # Q&A affordance; domain default is off
        "enable_emoji_reactions": True,  # silent acknowledgement during a talk
        "enable_network_ui": True,       # participants can see their own connection
    }
    if settings.DAILY_MAX_PARTICIPANTS:
        props["max_participants"] = settings.DAILY_MAX_PARTICIPANTS
    return props


def room_owner_for_event(event, *, create: bool = False):
    """Who owns the Daily room an event meets in.

    Offering events (seminar / reading group / cartel) *are* their workgroup, so
    they meet in the workgroup's room. One-off events (special events, Days of
    Assembly, Working Days, Scholarly Seminars) own their own room rather than
    sharing the Programming Committee's — see task #463.

    ``create=True`` provisions the workgroup for an offering that lacks one;
    read-only callers leave it False and get None.
    """
    from events.models import Event

    if event.event_type not in Event.ANNUAL_PROGRAM_TYPES:
        return event
    if event.workgroup is not None:
        return event.workgroup
    return event.ensure_workgroup() if create else None


def ensure_room(owner) -> DailyRoom | None:
    """Return the owner's Daily room, reconciling our DB row against Daily.

    Daily is the source of truth: we verify the room still exists on every call
    and recreate it if it was deleted (e.g. cleaned up in the Daily dashboard), so
    a stale DB row can't hand out a dead "meeting does not exist" URL. ``owner`` is
    a Workgroup or a Parlêtre Channel (both expose ``video_room``). Returns ``None``
    when the feature is disabled or the Daily call fails.
    """
    if not daily_enabled():
        return None

    room = getattr(owner, "video_room", None)
    name = room.name if room is not None else _room_name(owner)
    properties = _desired_properties(owner)

    try:
        data = daily.get_room(name)  # None if it was deleted on Daily's side
        if data is None:
            data = daily.create_room(name, properties=properties)
        else:
            # Reconcile every property we own, not just recording — a room created
            # before a property was added would otherwise never receive it.
            config = data.get("config") or {}
            drift = {
                key: value
                for key, value in properties.items()
                if _norm(config.get(key)) != _norm(value)
            }
            if drift:
                logger.info(
                    "Daily room %s config drifted, reconciling %s", name, sorted(drift)
                )
                data = daily.update_room(name, drift) or data
    except daily.DailyError:
        logger.exception("Daily ensure_room failed for %s", name)
        return None

    url = data.get("url") or f"https://{settings.DAILY_DOMAIN}/{name}"
    if room is None:
        if _is_workgroup(owner):
            owner_kwarg = {"workgroup": owner}
        elif _is_event(owner):
            owner_kwarg = {"event": owner}
        else:
            owner_kwarg = {"channel": owner}
        room = DailyRoom.objects.create(
            name=name, url=url, provider_created=True, **owner_kwarg
        )
    else:
        room.url = url
        room.provider_created = True
        room.save(update_fields=["url", "provider_created", "last_synced_at"])
    return room


def token_exp_for(event, now=None) -> int | None:
    """Unix expiry covering the rest of ``event``'s current joinable window, or
    None when there isn't one — a host opening the room days early, or a
    workgroup/channel room with no event context. The caller then falls back to
    the flat ``DAILY_TOKEN_TTL_MINUTES``.

    The flat TTL (180 min) is shorter than a long event's joinable window
    (``JOIN_PREOPEN`` + session + ``JOIN_GRACE``), so without this a participant
    rejoining after a network blip late in a three-hour event presents an
    expired token. Daily does not eject at ``exp`` (``eject_at_token_exp``
    defaults false), so the failure mode is rejoin only.
    """
    if event is None:
        return None
    session = event.live_session(now)
    if session is None:
        return None
    return int((session.end_at + type(event).JOIN_GRACE).timestamp())


def mint_token(
    room: DailyRoom, user, *, is_owner: bool = False, start_off: bool = False,
    exp: int | None = None,
) -> str:
    """A short-lived meeting token for ``user`` to join ``room``.

    ``start_off`` joins the participant muted + camera-off (speaker spotlight);
    it's soft, so they can turn them back on. ``exp`` extends the token to cover
    an event's joinable window; it never shortens it below the flat default.
    """
    default_exp = int(time.time()) + settings.DAILY_TOKEN_TTL_MINUTES * 60
    exp = max(default_exp, exp) if exp else default_exp
    name = ""
    if user is not None:
        name = (getattr(user, "get_full_name", lambda: "")() or "").strip()
        name = name or getattr(user, "email", "") or ""
    return daily.create_meeting_token(
        room_name=room.name, user_name=name[:255], is_owner=is_owner, exp=exp,
        start_audio_off=start_off, start_video_off=start_off,
    )


def spotlight_start_off(room_owner, is_owner_flag: bool) -> bool:
    """Whether this participant should join with A/V off (task #463).

    Only a non-owner (an attendee) of a one-off Event whose ``speaker_spotlight``
    is on starts muted + camera-off; the speaker/hosts (owners) never do.
    Workgroup-owned rooms (offerings) are unaffected.
    """
    if is_owner_flag:
        return False
    return bool(_is_event(room_owner) and getattr(room_owner, "speaker_spotlight", False))


def system_check_context(request) -> dict:
    """A throwaway pre-event device/network check room. Each call mints a fresh
    private room that auto-closes ~10 min after creation (``exp`` +
    ``eject_at_room_exp``) so testing never touches a real event room. Returns
    ``{room_url, room_token}`` or ``{room_unavailable: True}``."""
    if not daily_enabled():
        return {"room_unavailable": True}
    name = f"{ROOM_PREFIX}check-{uuid.uuid4().hex[:16]}"
    exp = int(time.time()) + 600  # ~10 minutes
    user = getattr(request, "user", None)
    uname = ""
    if user is not None:
        uname = (getattr(user, "get_full_name", lambda: "")() or "").strip()
        uname = uname or getattr(user, "email", "") or ""
    try:
        data = daily.create_room(name, properties={
            "enable_prejoin_ui": True,
            "enable_chat": False,
            "enable_recording": False,
            "exp": exp,
            "eject_at_room_exp": True,
        })
        token = daily.create_meeting_token(
            room_name=name, user_name=uname[:255], is_owner=False, exp=exp
        )
    except daily.DailyError:
        logger.exception("Daily system-check provisioning failed")
        return {"room_unavailable": True}
    url = data.get("url") or f"https://{settings.DAILY_DOMAIN}/{name}"
    return {"room_url": url, "room_token": token}


# ---- recordings (webhook ingestion) ------------------------------------

def _recording_event_and_title(room):
    """Resolve the event + a default title for a recording in ``room``."""
    event = None
    if room is not None and room.event_id:
        event = room.event  # a one-off event owns its room directly
    elif room is not None and room.workgroup_id:
        event = room.workgroup.primary_event() or room.workgroup.current_term()
    name = (event.title if event else (room.workgroup.name if room and room.workgroup_id
            else (room.name if room else "Recording")))
    return event, name


def ingest_recording_event(event_type: str, payload: dict):
    """Upsert a Recording from a Daily recording webhook. Idempotent on the Daily
    recording id. Returns the Recording or None."""
    from datetime import datetime
    from datetime import timezone as _tz

    from .models import DailyRoom, Recording

    rec_id = payload.get("recording_id") or payload.get("id")
    if not rec_id:
        return None
    room_name = payload.get("room_name") or payload.get("room") or ""
    room = DailyRoom.objects.filter(name=room_name).first()
    event, default_name = _recording_event_and_title(room)

    rec, created = Recording.objects.get_or_create(
        daily_recording_id=rec_id,
        defaults={"room": room, "room_name": room_name, "event": event},
    )
    if created and event is not None and getattr(event, "record_video", False):
        # An event flagged to record → list it for members by default.
        rec.listing_visibility = Recording.Visibility.MEMBERS
        rec.content_visibility = Recording.Visibility.MEMBERS

    start_ts = payload.get("start_ts")
    if start_ts and not rec.started_at:
        rec.started_at = datetime.fromtimestamp(int(start_ts), tz=_tz.utc)

    if event_type == "recording.started":
        rec.status = Recording.Status.RECORDING
    elif event_type == "recording.ready-to-download":
        rec.status = Recording.Status.READY
        rec.s3_key = payload.get("s3_key") or payload.get("s3key") or rec.s3_key
        rec.duration_seconds = payload.get("duration") or rec.duration_seconds
        if not rec.title:
            stamp = rec.started_at.date().isoformat() if rec.started_at else ""
            rec.title = f"{default_name} — {stamp}".strip(" —")
    elif event_type == "recording.error":
        rec.status = Recording.Status.ERROR
    rec.save()

    # Notify the group when a recording finishes and members may see it.
    if (
        event_type == "recording.ready-to-download"
        and rec.listing_visibility == Recording.Visibility.MEMBERS
    ):
        from workgroups import notifications as notify_groups
        notify_groups.recording_ready(rec)
    return rec


def can_enter(owner, user) -> bool:
    """Whether ``user`` may join the room (the access primitive). ``owner`` is a
    Workgroup or a one-off Event that owns its own room."""
    if _is_event(owner):
        return can_enter_event(owner, user)
    return owner.is_member(user)


def can_enter_event(event, user) -> bool:
    """Room access for an event that owns its own room: paid/comped registrants,
    the event's hosts (faculty/PC/staff)."""
    if not getattr(user, "is_authenticated", False):
        return False
    if event.has_access_registrant(user):
        return True
    from events.permissions import can_edit_event

    return can_edit_event(user, event)


def is_owner(owner, user) -> bool:
    """Whether ``user`` should join as a moderator (owner controls)."""
    if _is_event(owner):
        from events.permissions import can_edit_event

        return can_edit_event(user, owner)
    event = owner.primary_event() or owner.current_term()
    if event is not None:
        from events.permissions import can_edit_event

        if can_edit_event(user, event):
            return True
    from workgroups.models import WorkgroupMembership

    return owner.memberships.serving().filter(
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


def participant_names(people) -> list[str]:
    """Display names of the participants in a presence list (deduped, in join
    order). Daily sets ``userName`` from the meeting token."""
    seen: set[str] = set()
    names: list[str] = []
    for p in people or []:
        n = (p.get("userName") or p.get("user_name") or "").strip()
        key = n.lower()
        if n and key not in seen:
            seen.add(key)
            names.append(n)
    return names


def presence_names(room) -> list[str]:
    """Who is currently in a ``DailyRoom`` (or None) — names for the 'who's in
    the room' lists. Empty when the room is unprovisioned / empty."""
    if room is None:
        return []
    return participant_names(presence_map().get(room.name, []))


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
    recording_available = getattr(owner, "recording_mode", "on_demand") != "off"
    return {
        "room_url": room.url, "room_token": token, "is_owner": owner_flag,
        "recording_available": recording_available,
    }
