# Event Video Meeting Test — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Daily-backed room for *Working with Masochism* (2026-09-06) provably correct before the event, and leave behind a reusable pre-flight check for every future online event.

**Architecture:** All room configuration flows through one function, `video.services.ensure_room`, which currently applies its property set only at room creation. Phase 1 makes that function reconcile its full property set against the live room, adds the missing Q&A properties, makes meeting-token lifetime cover the real joinable window, closes the access-matrix test gaps, and adds a strictly read-only `manage.py event_video_preflight` that reports the **live** room config rather than the intended one.

**Tech Stack:** Django 5.2, pytest-django, Daily.co REST API (`video/daily.py`), uv.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-26-event-video-meeting-test-design.md`. Read it first.
- **Local pytest only.** The suite is fully stubbed (`DAILY_ENABLED` defaults false, `@daily_on` uses a fake key, `video/tests/test_views.py:13` monkeypatches provisioning). Never run pytest against prod — it creates and drops a test database.
- **Anything that actually talks to Daily runs on prod**, where the credentials live. Prod access is authorized via `ssh lsp` or SSM (instance `i-070b087afa041f233`, service `web_green`, wrap in `sudo -iu ec2-user`).
- Daily normalizes a falsy `enable_recording` to the **string `"0"`** on read-back. Every room-config comparison must normalize, or `ensure_room` will fire an update API call on every join.
- `enable_hand_raising`, `enable_emoji_reactions`, `enable_network_ui` are confirmed valid **room-level** properties (probed 2026-07-26); room properties override the domain defaults. No Daily dashboard change is needed.
- Meeting tokens: `eject_at_token_exp` defaults false, so an expiring token does **not** eject a participant mid-call. The failure mode is rejoin only.
- Run `uv run ruff check .` before each commit.
- Do **not** open the Masochism room by hand until Task 1 and Task 2 are deployed (Task 7 provisions it deliberately).

---

### Task 1: Reconcile the full room property set (R1, blocking)

`ensure_room` builds a full property dict but, when the room already exists on Daily, reconciles exactly one key — `enable_recording` (`video/services.py:96-100`). Every other property is create-time only, so a room opened before a config change silently keeps stale config. This is the blocking fix.

**Files:**
- Modify: `video/services.py:82-120`
- Test: `video/tests/test_services.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `services._desired_properties(owner) -> dict` (the single source of truth for a room's intended config; Task 2 extends it, Task 6 compares against it) and `services._norm(value)` (Daily config value normalizer).

- [ ] **Step 1: Write the failing tests**

Add to `video/tests/test_services.py`:

```python
@daily_on
def test_ensure_room_does_not_update_when_config_matches(monkeypatch):
    # No drift -> no write. Guards against an update call on every single join.
    wg = seminar().ensure_workgroup()
    config = dict(services._desired_properties(wg))
    monkeypatch.setattr(
        "video.daily.get_room",
        lambda name: {"name": name, "url": f"https://x/{name}", "config": config},
    )
    updates: list = []
    monkeypatch.setattr(
        "video.daily.update_room", lambda name, props: updates.append(props) or {}
    )
    services.ensure_room(wg)
    assert updates == []


@daily_on
def test_ensure_room_tolerates_daily_string_zero_for_recording(monkeypatch):
    # Daily stores a falsy enable_recording as the STRING "0". A naive equality
    # check reads that as permanent drift and rewrites the room on every join.
    wg = seminar().ensure_workgroup()
    wg.recording_mode = "off"
    wg.save(update_fields=["recording_mode"])
    config = dict(services._desired_properties(wg))
    assert config["enable_recording"] is False
    config["enable_recording"] = "0"  # what Daily actually returns
    monkeypatch.setattr(
        "video.daily.get_room",
        lambda name: {"name": name, "url": f"https://x/{name}", "config": config},
    )
    updates: list = []
    monkeypatch.setattr(
        "video.daily.update_room", lambda name, props: updates.append(props) or {}
    )
    services.ensure_room(wg)
    assert updates == []


@daily_on
def test_ensure_room_reconciles_every_drifted_property(monkeypatch):
    # R1: a room created before a property existed must receive it — the old
    # code only ever reconciled enable_recording.
    wg = seminar().ensure_workgroup()
    config = dict(services._desired_properties(wg))
    config.pop("enable_people_ui")   # room predates the property
    config["enable_chat"] = False    # and one drifted underneath us
    monkeypatch.setattr(
        "video.daily.get_room",
        lambda name: {"name": name, "url": f"https://x/{name}", "config": config},
    )
    updates: list = []
    monkeypatch.setattr(
        "video.daily.update_room",
        lambda name, props: updates.append(props)
        or {"name": name, "url": f"https://x/{name}"},
    )
    services.ensure_room(wg)
    assert updates == [{"enable_people_ui": True, "enable_chat": True}]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest video/tests/test_services.py -k "matches or string_zero or drifted" -v`
Expected: FAIL — `AttributeError: module 'video.services' has no attribute '_desired_properties'`

- [ ] **Step 3: Implement**

In `video/services.py`, add above `ensure_room`:

```python
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
    }
    if settings.DAILY_MAX_PARTICIPANTS:
        props["max_participants"] = settings.DAILY_MAX_PARTICIPANTS
    return props
```

Then replace the body of `ensure_room` from the `properties = {...}` literal through the `except` block with:

```python
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
                    "Daily room %s config drifted, reconciling %s",
                    name, sorted(drift),
                )
                data = daily.update_room(name, drift) or data
    except daily.DailyError:
        logger.exception("Daily ensure_room failed for %s", name)
        return None
```

- [ ] **Step 4: Run the full video suite**

Run: `uv run pytest video/ -v`
Expected: PASS, including the pre-existing `test_ensure_room_reconciles_recording_toggle` (its `config` lacks every other key, so the drift dict contains them all — assert that its `updates[0]["enable_recording"] is False` assertion still holds; it does, since it indexes by key).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && git add video/services.py video/tests/test_services.py && git commit -m "Video: reconcile the full Daily room property set, not just recording (task #475)"
```

---

### Task 2: Add hand-raising, reactions, and the network indicator (R4)

Domain-level defaults have `enable_hand_raising`, `enable_emoji_reactions`, and `enable_network_ui` off, so a lecture with Q&A has no raise-hand affordance. Probed 2026-07-26: all three are valid room-level properties and override the domain default.

**Files:**
- Modify: `video/services.py` (`_desired_properties`)
- Test: `video/tests/test_services.py`

**Interfaces:**
- Consumes: `services._desired_properties` from Task 1.
- Produces: nothing new.

- [ ] **Step 1: Write the failing tests**

```python
@daily_on
def test_new_rooms_get_qa_affordances(monkeypatch):
    # A talk with Q&A needs raise-hand and reactions; the Daily domain defaults
    # have them off, so the room properties must turn them on.
    calls: list = []
    monkeypatch.setattr("video.daily.get_room", _missing)
    monkeypatch.setattr("video.daily.create_room", _fake_create_room(calls))
    wg = seminar().ensure_workgroup()
    services.ensure_room(wg)
    props = calls[0]["properties"]
    assert props["enable_hand_raising"] is True
    assert props["enable_emoji_reactions"] is True
    assert props["enable_network_ui"] is True


@daily_on
def test_existing_room_is_upgraded_with_qa_affordances(monkeypatch):
    # The rooms already on the account predate these properties; reconciliation
    # must push them out rather than waiting for a room to be recreated.
    wg = seminar().ensure_workgroup()
    config = dict(services._desired_properties(wg))
    for key in ("enable_hand_raising", "enable_emoji_reactions", "enable_network_ui"):
        config.pop(key)
    monkeypatch.setattr(
        "video.daily.get_room",
        lambda name: {"name": name, "url": f"https://x/{name}", "config": config},
    )
    updates: list = []
    monkeypatch.setattr(
        "video.daily.update_room",
        lambda name, props: updates.append(props)
        or {"name": name, "url": f"https://x/{name}"},
    )
    services.ensure_room(wg)
    assert updates == [{
        "enable_hand_raising": True,
        "enable_emoji_reactions": True,
        "enable_network_ui": True,
    }]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest video/tests/test_services.py -k "qa_affordances" -v`
Expected: FAIL with `KeyError: 'enable_hand_raising'`

- [ ] **Step 3: Implement**

In `_desired_properties`, add to the `props` dict after `"enable_people_ui": True,`:

```python
        "enable_hand_raising": True,     # Q&A affordance; domain default is off
        "enable_emoji_reactions": True,  # silent acknowledgement during a talk
        "enable_network_ui": True,       # participants can see their own connection
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest video/ -v`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && git add video/services.py video/tests/test_services.py && git commit -m "Video: enable hand-raising, reactions, and the network indicator in rooms (task #475)"
```

---

### Task 3: Make token lifetime cover the joinable window (R3)

`DAILY_TOKEN_TTL_MINUTES` is a flat 180. The Masochism joinable window is 3h15m (`JOIN_PREOPEN` 15 min + a 3h session, `events/models.py:674-675`). A participant who rejoins after a network blip late in the event presents an expired token. Confirmed 2026-07-26 that Daily does not eject at `exp` (`eject_at_token_exp` defaults false), so this is a rejoin failure, not a mid-talk ejection.

**Files:**
- Modify: `video/services.py` (`mint_token`, new `token_exp_for`)
- Modify: `video/views.py:187-190`
- Test: `video/tests/test_services.py`, `video/tests/test_views.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `services.token_exp_for(event, now=None) -> int | None` and `services.mint_token(room, user, *, is_owner=False, start_off=False, exp=None) -> str`.

- [ ] **Step 1: Write the failing tests**

In `video/tests/test_services.py`:

```python
def test_token_exp_for_covers_session_end_plus_grace():
    from datetime import timedelta

    from django.utils import timezone

    from events.models import Event, Session

    ev = special_event(slug="ttl-live")
    start = timezone.now() - timedelta(minutes=5)
    session = Session.objects.create(
        event=ev, sequence=1, start_at=start, end_at=start + timedelta(hours=3)
    )
    exp = services.token_exp_for(ev)
    assert exp == int((session.end_at + Event.JOIN_GRACE).timestamp())


def test_token_exp_for_is_none_outside_the_live_window():
    # A host opening the room days early gets the flat default, not a huge TTL.
    from datetime import timedelta

    from django.utils import timezone

    from events.models import Session

    ev = special_event(slug="ttl-early")
    start = timezone.now() + timedelta(days=3)
    Session.objects.create(
        event=ev, sequence=1, start_at=start, end_at=start + timedelta(hours=3)
    )
    assert services.token_exp_for(ev) is None
    assert services.token_exp_for(None) is None


@daily_on
def test_mint_token_never_shortens_below_the_default_ttl(monkeypatch):
    import time as _time

    seen: dict = {}
    monkeypatch.setattr(
        "video.daily.create_meeting_token",
        lambda **kw: seen.update(kw) or "tok",
    )
    room = DailyRoom.objects.create(
        name="lsp-ttl", url="https://x/lsp-ttl", provider_created=True,
        workgroup=seminar(slug="ttl-wg").ensure_workgroup(),
    )
    u = user("ttl@x.test")
    # An exp already in the past must not shrink the token's life.
    services.mint_token(room, u, exp=int(_time.time()) - 10)
    assert seen["exp"] >= int(_time.time()) + 170 * 60
```

In `video/tests/test_views.py`:

```python
@daily_on
def test_event_room_token_covers_the_whole_joinable_window(client, monkeypatch):
    # A three-hour session outlives the flat 180-minute TTL, so a late rejoin
    # would otherwise present an expired token.
    from datetime import timedelta

    from django.utils import timezone

    from events.models import Event, Session

    from .factories import register, special_event

    seen: dict = {}
    monkeypatch.setattr(
        "video.daily.create_meeting_token", lambda **kw: seen.update(kw) or "tok"
    )
    ev = special_event(slug="window")
    start = timezone.now() - timedelta(minutes=10)
    session = Session.objects.create(
        event=ev, sequence=1, start_at=start, end_at=start + timedelta(hours=3)
    )
    attendee = user("w@x.test")
    register(attendee, ev)
    client.force_login(attendee)
    assert client.get(f"/events/{ev.slug}/room/").status_code == 200
    assert seen["exp"] >= int((session.end_at + Event.JOIN_GRACE).timestamp())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest video/tests/test_services.py -k token_exp video/tests/test_views.py -k joinable_window -v`
Expected: FAIL — `AttributeError: module 'video.services' has no attribute 'token_exp_for'`

- [ ] **Step 3: Implement**

In `video/services.py`, add after `mint_token`:

```python
def token_exp_for(event, now=None) -> int | None:
    """Unix expiry covering the rest of ``event``'s current joinable window, or
    None when there isn't one — a host opening the room days early, or a
    workgroup/channel room with no event context. The caller then falls back to
    the flat ``DAILY_TOKEN_TTL_MINUTES``.

    The flat TTL (180 min) is shorter than a long event's joinable window
    (``JOIN_PREOPEN`` + session + ``JOIN_GRACE``), so without this a participant
    rejoining after a network blip late in a three-hour event presents an
    expired token.
    """
    if event is None:
        return None
    session = event.live_session(now)
    if session is None:
        return None
    return int((session.end_at + type(event).JOIN_GRACE).timestamp())
```

Change `mint_token`'s signature and expiry line:

```python
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
```

In `video/views.py`, change the `_render_room` mint call:

```python
        token = services.mint_token(
            room, request.user, is_owner=owner, start_off=start_off,
            exp=services.token_exp_for(event),
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest video/ -v`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && git add video/services.py video/views.py video/tests/ && git commit -m "Video: meeting tokens cover the event's whole joinable window (task #475)"
```

---

### Task 4: Close the access-matrix test gaps

These are the cases that produce "I registered and I can't get in" on the day. All assert existing intended behavior — they are regression coverage, and any that fails is a bug found.

**Files:**
- Modify: `video/tests/test_event_rooms.py`

**Interfaces:**
- Consumes: `services.spotlight_start_off` (existing), the Task 1-3 changes.
- Produces: nothing.

- [ ] **Step 1: Write the tests**

Append to `video/tests/test_event_rooms.py` (extend the existing factory import line to `from .factories import daily_on, register, seminar, special_event, user`):

```python
def test_pending_and_cancelled_registrations_are_denied():
    # Only PAID/COMPED grant access. An unpaid or cancelled row must not.
    from registrations.models import Registration

    ev = special_event(slug="statuses")
    for status in (
        Registration.Status.AWAITING_PAYMENT,
        Registration.Status.CANCELLED,
        Registration.Status.REFUNDED,
    ):
        u = user(f"{status}@x.test")
        register(u, ev, status=status)
        assert services.can_enter_event(ev, u) is False, status


def test_comped_registration_is_admitted():
    # Comping is the do-not-over-automate escape hatch; it must open the room.
    from registrations.models import Registration

    ev = special_event(slug="comped")
    u = user("comp@x.test")
    register(u, ev, status=Registration.Status.COMPED)
    assert services.can_enter_event(ev, u) is True


def test_treasurer_suspension_cuts_room_access():
    # Profile.seminar_access_suspended is a manual, audited treasurer action;
    # has_access_registrant honours it, so the room must too.
    ev = special_event(slug="suspended")
    u = user("susp@x.test")
    register(u, ev)
    assert services.can_enter_event(ev, u) is True
    u.profile.seminar_access_suspended = True
    u.profile.save(update_fields=["seminar_access_suspended"])
    u.refresh_from_db()
    assert services.can_enter_event(ev, u) is False


def test_anonymous_visitor_is_redirected_to_login_not_403(client):
    # Gated GET pages redirect anonymous users to login with ?next= — only
    # signed-in non-members get a 403. Covered for seminars; this is the
    # event-owned-room path.
    ev = special_event(slug="anon-event")
    resp = client.get(f"/events/{ev.slug}/room/")
    assert resp.status_code == 302
    assert "/accounts/login" in resp.url or "/login" in resp.url


def test_spotlight_mutes_attendees_but_never_the_speaker():
    # The speaker keeps A/V; attendees land muted + camera-off, softly.
    ev = special_event(slug="spot-matrix")
    ev.speaker_spotlight = True
    ev.save(update_fields=["speaker_spotlight"])
    host = user("spot-host@x.test", is_faculty=True)
    ev.add_faculty(host)
    attendee = user("spot-att@x.test")
    register(attendee, ev)
    assert services.spotlight_start_off(ev, services.is_owner(ev, host)) is False
    assert services.spotlight_start_off(ev, services.is_owner(ev, attendee)) is True


@daily_on
def test_spotlight_reaches_the_minted_token(client, monkeypatch):
    # The flag is worthless unless it actually lands on the token.
    seen: dict = {}
    monkeypatch.setattr("video.daily.get_room", lambda name: None)
    monkeypatch.setattr(
        "video.daily.create_room",
        lambda name, *, properties=None: {"name": name, "url": f"https://x/{name}"},
    )
    monkeypatch.setattr(
        "video.daily.create_meeting_token", lambda **kw: seen.update(kw) or "tok"
    )
    ev = special_event(slug="spot-token")
    ev.speaker_spotlight = True
    ev.save(update_fields=["speaker_spotlight"])
    attendee = user("spot-tok@x.test")
    register(attendee, ev)
    client.force_login(attendee)
    assert client.get(f"/events/{ev.slug}/room/").status_code == 200
    assert seen.get("start_audio_off") is True
    assert seen.get("start_video_off") is True
```

- [ ] **Step 2: Run them**

Run: `uv run pytest video/tests/test_event_rooms.py -v`
Expected: PASS. **If any fail, stop** — that is a real access bug, not a test bug. Fix the code, not the assertion, and note it in the task.

`Registration.Status` members confirmed against `registrations/models.py:13-20`: `PENDING_APPROVAL`, `AWAITING_PAYMENT`, `PAID`, `COMPED`, `DECLINED`, `CANCELLED`, `REFUNDED`.

- [ ] **Step 3: Lint and commit**

```bash
uv run ruff check . && git add video/tests/test_event_rooms.py && git commit -m "Video: cover the event-room access matrix — comped, suspended, cancelled, spotlight (task #475)"
```

---

### Task 5: Extract `room_owner_for_event`

The "offering events meet in their workgroup's room, one-off events own theirs" branch is written out three times (`video/views.py:51-55`, `events/views.py:84-88`, and implicitly in the new command). Three copies of an access-control branch is how they drift apart.

**Files:**
- Modify: `video/services.py`, `video/views.py:45-59`, `events/views.py:84-88`
- Test: `video/tests/test_event_rooms.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `services.room_owner_for_event(event, *, create=False)` returning a `Workgroup` for annual-program events, the `Event` itself for one-off events, or `None` when an offering has no workgroup and `create=False`.

- [ ] **Step 1: Write the failing test**

```python
def test_room_owner_for_event_splits_offerings_from_one_offs():
    sem = seminar(slug="owner-sem")
    wg = sem.ensure_workgroup()
    assert services.room_owner_for_event(sem) == wg
    ev = special_event(slug="owner-special")
    assert services.room_owner_for_event(ev) == ev


def test_room_owner_for_event_does_not_create_a_workgroup_by_default():
    sem = seminar(slug="owner-nocreate")
    assert services.room_owner_for_event(sem) is None
    assert services.room_owner_for_event(sem, create=True) == sem.workgroup
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest video/tests/test_event_rooms.py -k room_owner_for_event -v`
Expected: FAIL — `AttributeError: module 'video.services' has no attribute 'room_owner_for_event'`

- [ ] **Step 3: Implement**

In `video/services.py`:

```python
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
```

In `video/views.py`, replace the branch in `event_room`:

```python
@login_required
def event_room(request, slug):
    event = get_object_or_404(Event, slug=slug)
    owner = services.room_owner_for_event(event, create=True)
    if owner is None:
        raise Http404("This event has no meeting room.")
    return _render_room(
        request, owner, event=event, back_url=reverse("events:detail", args=[event.slug])
    )
```

In `events/views.py`, replace lines 84-88 with:

```python
    from video.services import room_owner_for_event

    owner = room_owner_for_event(event)  # read-only: never provisions
    room = getattr(owner, "video_room", None) if owner is not None else None
```

(Delete the now-unused `wg = getattr(event, "workgroup", None)` line if nothing else below uses it — grep the rest of the function first.)

- [ ] **Step 4: Run the tests**

Run: `uv run pytest video/ events/ -v`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && git add video/services.py video/views.py events/views.py video/tests/test_event_rooms.py && git commit -m "Video: one helper for which room an event meets in (task #475)"
```

---

### Task 6: `manage.py event_video_preflight <slug>`

A green/red report for any online event, **strictly read-only by default** so running the check cannot itself provision a room and freeze its config.

**Files:**
- Create: `video/management/commands/event_video_preflight.py`
- Test: `video/tests/test_preflight.py`

**Interfaces:**
- Consumes: `services._desired_properties`, `services._norm`, `services.room_owner_for_event`, `services._room_name`, `services.can_enter`, `services.is_owner`, `services.token_exp_for`.
- Produces: a command exiting non-zero when any check FAILs.

- [ ] **Step 1: Write the failing test**

Create `video/tests/test_preflight.py`:

```python
from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from .factories import daily_on, register, special_event, user

pytestmark = pytest.mark.django_db


@daily_on
def test_preflight_is_read_only_by_default(monkeypatch):
    # The whole point: running the check must never provision the room.
    created: list = []
    monkeypatch.setattr("video.daily.get_room", lambda name: None)
    monkeypatch.setattr(
        "video.daily.create_room",
        lambda name, *, properties=None: created.append(name) or {"name": name},
    )
    monkeypatch.setattr("video.daily.get_presence", lambda: {})
    ev = special_event(slug="pf-readonly")
    out = StringIO()
    with pytest.raises(SystemExit):
        call_command("event_video_preflight", ev.slug, stdout=out)
    assert created == []
    assert "not provisioned" in out.getvalue().lower()


@daily_on
def test_preflight_reports_live_room_property_drift(monkeypatch):
    # It must compare against the LIVE config, not the intended properties.
    from video import services

    ev = special_event(slug="pf-drift")
    config = dict(services._desired_properties(ev))
    config["enable_hand_raising"] = False
    monkeypatch.setattr(
        "video.daily.get_room",
        lambda name: {"name": name, "url": f"https://x/{name}", "config": config},
    )
    monkeypatch.setattr("video.daily.get_presence", lambda: {})
    out = StringIO()
    with pytest.raises(SystemExit):
        call_command("event_video_preflight", ev.slug, stdout=out)
    assert "enable_hand_raising" in out.getvalue()


@daily_on
def test_preflight_passes_a_correctly_configured_event(monkeypatch):
    from video import services

    ev = special_event(slug="pf-ok")
    ev.speaker_spotlight = True
    ev.save(update_fields=["speaker_spotlight"])
    host = user("pf-host@x.test", is_faculty=True)
    ev.add_faculty(host)
    register(user("pf-att@x.test"), ev)
    config = dict(services._desired_properties(ev))
    monkeypatch.setattr(
        "video.daily.get_room",
        lambda name: {"name": name, "url": f"https://x/{name}", "config": config},
    )
    monkeypatch.setattr("video.daily.get_presence", lambda: {})
    out = StringIO()
    call_command("event_video_preflight", ev.slug, stdout=out)  # no SystemExit
    assert "FAIL" not in out.getvalue()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest video/tests/test_preflight.py -v`
Expected: FAIL — `CommandError: Unknown command: 'event_video_preflight'`

- [ ] **Step 3: Implement**

Create `video/management/commands/event_video_preflight.py`:

```python
"""Pre-flight report for an online event's video meeting (task #475).

Read-only by default: it reports the room's **live** config, never the config we
intended, and never provisions the room — creating a room freezes its property
set at whatever the code said that day (see the
daily-room-config-freezes-at-first-open memory), so a check must not do it as a
side effect. Pass --provision when you deliberately want the room minted.

    manage.py event_video_preflight working-with-masochism
"""
from __future__ import annotations

import sys

from django.core.management.base import BaseCommand, CommandError

from events.models import Event
from video import daily, services

OK, WARN, FAIL = "ok", "WARN", "FAIL"


class Command(BaseCommand):
    help = "Read-only pre-flight report for an online event's video meeting."

    def add_arguments(self, parser):
        parser.add_argument("slug", help="Event slug, e.g. working-with-masochism")
        parser.add_argument(
            "--provision", action="store_true",
            help="Also create/reconcile the Daily room (default is read-only).",
        )

    def handle(self, *args, **options):
        try:
            event = Event.objects.get(slug=options["slug"])
        except Event.DoesNotExist as exc:
            raise CommandError(f"No event with slug {options['slug']!r}") from exc

        rows: list[tuple[str, str, str]] = []
        rows.extend(self._check_feature())
        rows.extend(self._check_event(event))
        rows.extend(self._check_room(event, provision=options["provision"]))
        rows.extend(self._check_hosts(event))
        rows.extend(self._check_registrants(event))
        rows.extend(self._check_token_window(event))
        rows.extend(self._check_presence())

        self.stdout.write(f"\nPre-flight — {event.title} ({event.slug})\n")
        for status, label, detail in rows:
            style = {
                OK: self.style.SUCCESS, WARN: self.style.WARNING, FAIL: self.style.ERROR
            }[status]
            self.stdout.write(f"  {style(status.upper().ljust(5))} {label}: {detail}")

        failures = [r for r in rows if r[0] == FAIL]
        warnings = [r for r in rows if r[0] == WARN]
        self.stdout.write(
            f"\n{len(rows)} checks, {len(failures)} failed, {len(warnings)} warnings\n"
        )
        if failures:
            sys.exit(1)

    # -- checks ---------------------------------------------------------

    def _check_feature(self):
        if not services.daily_enabled():
            return [(FAIL, "daily", "disabled or credentials missing")]
        from django.conf import settings

        out = [(OK, "daily", f"enabled, domain {settings.DAILY_DOMAIN}")]
        out.append(
            (OK, "webhook", "secret set") if settings.DAILY_WEBHOOK_SECRET
            else (WARN, "webhook", "DAILY_WEBHOOK_SECRET unset — recordings won't ingest")
        )
        return out

    def _check_event(self, event):
        out = []
        if event.format == "in_person":
            out.append((WARN, "format", "in_person — no video room expected"))
        else:
            out.append((OK, "format", event.format))
        out.append(
            (OK, "published", f"status={event.status}") if event.published
            else (WARN, "published", f"unpublished, status={event.status}")
        )
        if event.speaker_spotlight:
            out.append((OK, "spotlight", "attendees join muted + camera-off"))
        else:
            out.append((WARN, "spotlight", "OFF — attendees arrive unmuted"))
        mode = getattr(event, "recording_mode", "on_demand")
        out.append((
            OK, "recording",
            f"record_video={event.record_video}, recording_mode={mode}",
        ))
        if not event.sessions.exists():
            out.append((WARN, "sessions", "none — join window falls back to the date span"))
        return out

    def _check_room(self, event, *, provision: bool):
        owner = services.room_owner_for_event(event, create=provision)
        if owner is None:
            return [(FAIL, "room", "offering event has no workgroup (run with --provision)")]
        name = services._room_name(owner)
        if provision:
            room = services.ensure_room(owner)
            if room is None:
                return [(FAIL, "room", f"{name}: provisioning failed")]
        try:
            data = daily.get_room(name)
        except daily.DailyError as exc:
            return [(FAIL, "room", f"{name}: {exc}")]
        if data is None:
            return [(
                WARN, "room",
                f"{name}: not provisioned yet (mints on first join; "
                f"--provision to do it now)",
            )]
        out = [(OK, "room", f"{name} exists")]
        config = data.get("config") or {}
        drift = {
            key: (config.get(key), value)
            for key, value in services._desired_properties(owner).items()
            if services._norm(config.get(key)) != services._norm(value)
        }
        if drift:
            detail = ", ".join(f"{k} is {a!r}, want {w!r}" for k, (a, w) in drift.items())
            out.append((FAIL, "room config", detail))
        else:
            out.append((OK, "room config", "matches"))
        return out

    def _check_hosts(self, event):
        # Three ways to be a host: a member speaker, an external Speaker with a
        # linked login (task #463), or faculty on the event's workgroup. Event
        # has no `faculty` M2M — that lives on EventProposal.
        owner = services.room_owner_for_event(event)
        hosts, seen = [], set()
        for u in (
            list(event.member_speakers.all())
            + [s.user for s in event.speakers.filter(user__isnull=False).select_related("user")]
            + event.faculty_members()
        ):
            if u is not None and u.pk not in seen:
                seen.add(u.pk)
                hosts.append(u)
        if not hosts:
            return [(WARN, "hosts", "no speakers or faculty on the event")]
        out = []
        for u in hosts:
            problems = []
            if not u.is_active:
                problems.append("inactive")
            if not getattr(getattr(u, "profile", None), "email_verified_at", None):
                problems.append("email unverified")
            if not u.has_usable_password():
                problems.append("no usable password (password reset will skip them)")
            if owner is not None and not services.can_enter(owner, u):
                problems.append("CANNOT ENTER")
            if owner is not None and not services.is_owner(owner, u):
                problems.append("not a moderator")
            out.append(
                (FAIL if problems else OK, "host", f"{u.email}: "
                 + (", ".join(problems) if problems else "active, can enter, moderator"))
            )
        return out

    def _check_registrants(self, event):
        from registrations.models import Registration

        ok = event.registrations.filter(
            status__in=(Registration.Status.PAID, Registration.Status.COMPED)
        ).count()
        pending = event.registrations.filter(
            status=Registration.Status.AWAITING_PAYMENT
        ).count()
        blocked = [
            r.user.email for r in event.registrations.filter(
                status__in=(Registration.Status.PAID, Registration.Status.COMPED)
            ).select_related("user__profile")
            if r.user and not services.can_enter(
                services.room_owner_for_event(event) or event, r.user
            )
        ]
        out = [(OK, "registrants", f"{ok} with access, {pending} awaiting payment")]
        if blocked:
            out.append((FAIL, "registrants", f"paid but cannot enter: {', '.join(blocked)}"))
        return out

    def _check_token_window(self, event):
        from django.conf import settings

        ttl = settings.DAILY_TOKEN_TTL_MINUTES
        session = event.sessions.order_by("start_at").last()
        if session is None:
            return [(OK, "token window", f"flat TTL {ttl} min (no sessions)")]
        window = (
            (session.end_at + Event.JOIN_GRACE)
            - (session.start_at - Event.JOIN_PREOPEN)
        ).total_seconds() / 60
        if window <= ttl:
            return [(OK, "token window", f"{window:.0f} min window <= {ttl} min TTL")]
        return [(
            OK, "token window",
            f"{window:.0f} min window > {ttl} min flat TTL — covered by "
            f"token_exp_for() while the event is live",
        )]

    def _check_presence(self):
        try:
            daily.get_presence()
        except daily.DailyError as exc:
            return [(FAIL, "presence", str(exc))]
        return [(OK, "presence", "API reachable")]
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest video/tests/test_preflight.py -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && git add video/management/commands/event_video_preflight.py video/tests/test_preflight.py && git commit -m "Video: manage.py event_video_preflight — read-only room readiness report (task #475)"
```

---

### Task 7: Deploy and apply on prod

Code changes are worthless until the live room actually has the config. This task is the one that touches prod.

**Files:** none (operational).

**Interfaces:**
- Consumes: everything above.
- Produces: a provisioned, correctly configured `lsp-event-working-with-masochism`.

- [ ] **Step 1: Push and confirm the deploy went green**

```bash
git push origin rapid-willow
```

Then open a PR to `main` and merge, or push to `main` per the project's flow. **A push is not a deploy** — a single failing test silently aborts it. Verify the Deploy workflow run is green before continuing:

```bash
gh run list --repo ricopicone/lsp-website --workflow Deploy --limit 3
```

- [ ] **Step 2: Turn the spotlight on (R2)**

On prod, via SSM (`sudo -iu ec2-user`, service `web_green`):

```python
from events.models import Event
e = Event.objects.get(slug="working-with-masochism")
e.speaker_spotlight = True
e.save(update_fields=["speaker_spotlight"])
print(e.speaker_spotlight)
```

- [ ] **Step 3: Provision the room deliberately (1.4)**

```
manage.py event_video_preflight working-with-masochism --provision
```

Expected: room created, `room config: matches`, `spotlight: attendees join muted + camera-off`, hosts row green for `stephanieswales@gmail.com`.

- [ ] **Step 4: Re-run read-only and confirm it stays green**

```
manage.py event_video_preflight working-with-masochism
```

Expected: identical result, zero failures, and **no second room creation** (the command is read-only without `--provision`).

- [ ] **Step 5: Confirm the live room config directly**

Independently of our own comparison code, fetch the room from Daily and eyeball `config` for `enable_hand_raising`, `enable_emoji_reactions`, `enable_network_ui`, `enable_prejoin_ui`, `enable_people_ui`, `enable_chat`, and `enable_recording: "cloud"`.

- [ ] **Step 6: Walk the guest funnel (1.7)**

In a browser as a brand-new account: signup → email verification (POST-gated) → register for a test event → payment. This is the longest untested chain and the one strangers will be on. Record anything that snags.

- [ ] **Step 7: Report**

Write findings into task #475. Anything unresolved becomes a stated known risk with a mitigation.

---

### Task 8: Rehearsal runbook

**Files:**
- Create: `docs/event-video-rehearsal.md`

**Interfaces:**
- Consumes: the preflight command name and the prod procedure from Task 7.
- Produces: the phase 2 operating document.

- [ ] **Step 1: Write the runbook**

Sections, per the spec's Phase 2:

1. **Before the rehearsal** — create the throwaway mirror event (same `format`, `speaker_spotlight`, `recording_mode`, `open_to_guests` as Masochism; session scheduled *at* the rehearsal time so `is_live()` is genuinely true; title unmistakably a rehearsal). Run `event_video_preflight <rehearsal-slug> --provision`.
2. **Cast and per-role scripts** — speaker, host, member attendee, guest attendee (brand-new account), latecomer, disruptor. One short script each, written so a non-technical participant can follow it.
3. **Beats** — T-15 pre-open → join at T-0 → everyone lands muted and camera-off → slides shared and legible → chat Q&A → hand-raise → host mutes the disruptor → start and stop a recording → force-refresh and rejoin → leave returns to the event page.
4. **Browser matrix** — Chrome, Safari on macOS and iOS, one Android.
5. **Checklist** — one line per beat, pass/fail, printable on a page.
6. **Teardown** — delete the rehearsal event; **registrations first**, both FKs are `PROTECT`.
7. **Known risks** — R5: a host who joins and leaves the tab open shows "Live now" to registrants for days and bills participant-minutes. Contained by the prejoin screen (opening the page does not join). Line item: close the tab.

- [ ] **Step 2: Commit**

```bash
git add docs/event-video-rehearsal.md && git commit -m "Docs: rehearsal runbook for the integrated event video meeting (task #475)"
```

---

## Self-review

**Spec coverage.** 1.1 → Task 1. 1.2 (V1/V2) → settled empirically before planning; results are Global Constraints, and V3 is folded into the runbook's known-risks section as accepted-and-mitigated rather than measured. 1.3 R2 → Task 7 step 2; R3 → Task 3; R4 → Task 2. 1.4 → Task 7 step 3. 1.5 → Task 6 (with the Task 5 extraction it depends on). 1.6 → Task 4. 1.7 → Task 7 step 6. Phase 2 → Task 8. Deliverables all covered.

**Deviation from the spec worth flagging.** The spec's 1.2 listed V3 (empty-session close timing) as an empirical probe. Measuring it means leaving a session idle for hours to observe when it closes, which buys little: the real containment for R5 is that the prejoin screen means opening the page does not join. Downgraded to a runbook line item. Anyone who wants it measured can do so during the rehearsal at no extra cost.

**Type consistency.** `_desired_properties(owner) -> dict` and `_norm(value)` (Task 1) are consumed by Task 2, Task 6. `token_exp_for(event, now=None) -> int | None` and `mint_token(..., exp=None)` (Task 3) are consumed by `video/views.py`. `room_owner_for_event(event, *, create=False)` (Task 5) is consumed by Task 6 and both view modules. Names match across tasks.
