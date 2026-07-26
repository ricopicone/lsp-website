# Integrated event video meeting — end-to-end test (task #475)

**Date:** 2026-07-26
**Status:** design approved, pending implementation
**Driver:** *Working with Masochism*, 2026-09-06, the school's first big online
special event on the integrated Daily rooms. A tech failure there is a public
failure of the new site.

## Goal

Prove the event runs without a tech incident, by testing the whole path a
participant walks, not just the video call:

> find the event → register (member **and** brand-new guest) → get in on the day
> → see and hear the speaker → ask a question → leave

and the host path: open the room early, moderate, optionally record.

**Non-goals.** Load testing (headroom is already measured — see *Measured
state*). A Zoom fallback (decision #463 stands: the in-site room *is* the join
path). Redesigning the room UI.

## Measured state (prod, 2026-07-26)

Established by read-only probes, not assumed.

**The event** — `working-with-masochism`, `special_event`, online, published,
registration OPEN, `open_to_guests=True`. One session, 2026-09-06
16:30–19:30 UTC (9:30am–12:30pm PDT). One registration (Rico, paid $100).
`record_video=False`, `speaker_spotlight=False`, `access_info` empty.
**No Daily room provisioned yet.**

Because `special_event` is not in `Event.ANNUAL_PROGRAM_TYPES`, the event owns
its own room (`lsp-event-working-with-masochism`) rather than sharing the
Programming Committee's — correct per the #463 design, confirmed in
`video/views.py:45-59`.

**The speaker** — `stephanieswales@gmail.com`: active, usable password, last
login 2026-07-23, email verified, `is_faculty`, on `member_speakers`. Computed
live on prod: `can_edit_event=True`, `can_enter=True`, `is_owner=True`. She gets
moderator controls and can open the room without registering. *The single
biggest anticipated risk is already clear.*

**The Daily account** — domain `lsp`, paid plan (`allow_plan_free: false`,
`hide_daily_branding: true`), recordings to `lsp-website-recordings-uswest2` via
`arn:aws:iam::…:role/lsp-daily-recordings` with `allow_api_access: true`.
Capacity is a non-issue: `default_max_meeting_producers: 2200`,
`default_max_user_subscriptions: 200`.

**Prod settings** — `DAILY_ENABLED=True`, domain `lsp.daily.co`, API key and
webhook secret both set, `DAILY_MAX_PARTICIPANTS=0` (unset),
`DAILY_TOKEN_TTL_MINUTES=180`. Daily is **off in local dev**, so anything that
must talk to Daily runs on prod.

## Risks found

### R1 — Room config freezes at first open *(blocking)*

`ensure_room` reconciles exactly one property against an already-existing room,
`enable_recording` (`video/services.py:96-100`). Every other property —
`enable_prejoin_ui`, `enable_chat`, `enable_people_ui`, and anything we add — is
applied **only at creation**.

So if anyone opens the room before the config changes land, the changes sit in
the code, the code reads correctly, and the live room silently lacks them. The
failure is invisible until the event.

Any host can trigger this today: the "Open room (host)" button shows regardless
of live-gating (`events/templates/events/_location.html:27`). Attendees cannot —
their Join only appears inside the live window.

Room *availability* is not at risk: event rooms carry no `exp` (only the
throwaway system-check rooms do), they are permanent and reused, and
`ensure_room` re-verifies against Daily every call and recreates a room deleted
on Daily's side.

### R2 — Attendees arrive unmuted

`speaker_spotlight=False` on this event. The feature built for exactly this case
(`services.spotlight_start_off`, task #463) is off, so ~60 people would arrive
live with cameras on.

### R3 — Token TTL is shorter than the joinable window

TTL is a flat 180 min; the joinable window is 3h15m (`JOIN_PREOPEN` 15 min +
a 3h session). Someone who opens the room at pre-open and later has to rejoin
after a network blip can hit an expired token. Whether Daily *ejects* at `exp`
or merely blocks new joins is unverified — see V2.

### R4 — No Q&A affordance

Domain-level `enable_hand_raising: false`, `enable_emoji_reactions: false`,
`enable_network_ui: false`. For a lecture with Q&A there is no raise-hand
affordance, only chat.

### R5 — Stale presence and billing from a joined tab

A host who joins and leaves the tab open shows "Live now · N in the room" to
registrants for days, and Daily bills participant-minutes throughout. Contained
by `enable_prejoin_ui: true` — opening the page lands on device-check, so you
are not counted until you click Join. The "Live now" block sits inside
`{% if has_paid_registration or can_host %}`, so it is never publicly visible.

## Recording decision

Leave `record_video=False` — nothing is recorded without a deliberate act, which
is the right default for a guest speaker who has not consented. Keep the event's
`recording_mode` at its default so the host still has a Record button and can
start recording in-meeting if Stephanie agrees. Rico is asking her. The full
recording chain is exercised in the rehearsal regardless, so the capability is
proven and the decision stays open.

## Phase 1 — pre-flight (solo)

Ordered. R1 is a prerequisite for everything that configures a room.

### 1.1 Fix property reconciliation (R1)

`ensure_room` reconciles its full intended property set against an existing
room, not just `enable_recording`. Land this before anything else so no window
remains in which someone can freeze the room's config.

### 1.2 Empirical verification against prod

Authorized to run live Daily calls from prod. Settle these on a throwaway room
rather than assuming:

- **V1** — are `enable_hand_raising`, `enable_emoji_reactions`,
  `enable_network_ui` accepted as *room* properties, or must they be set at the
  domain level? Determines how R4 is fixed.
- **V2** — does Daily eject a participant at token `exp`, or only refuse new
  joins? Determines how hard R3 must be fixed.
- **V3** — when does an empty session close (`empty_session_close_delay` is null
  at the domain)? Bounds the R5 billing exposure.

### 1.3 Apply the fixes

- **R2** → `speaker_spotlight=True` on the event.
- **R3** → for a room joined in the context of an event, derive the token TTL
  from that event's live window (session end + `JOIN_GRACE`) instead of the flat
  global, so a mid-meeting rejoin can never hit an expired token. Rooms with no
  event context (workgroup and channel rooms) keep the global default. Depth of
  fix informed by V2.
- **R4** → enable hand-raising, reactions, and the network indicator by
  whichever mechanism V1 establishes.

### 1.4 Provision the real room deliberately

Once 1.1 and 1.3 are in, provision and configure
`lsp-event-working-with-masochism` **on purpose**, and assert its live
properties. The event day must not depend on a cold first-create round-trip to
Daily succeeding.

### 1.5 `manage.py event_video_preflight <slug>`

A green/red report for any online event, **strictly read-only** — `get_room()`,
never `ensure_room()` — so running the check cannot itself provision a room. An
explicit `--provision` flag for when that is wanted.

Checks: Daily reachable and room resolvable; the **live room's actual
properties** (not the intended ones); every speaker/host account active,
verified, computing `can_enter` and `is_owner` true; the registrant access
predicate; token TTL against the real joinable window; recording mode and
destination bucket; webhook secret present; presence API reachable.

This outlives the rehearsal — it is the check to run a week before every online
event.

### 1.6 Close the automated test gaps

`video/tests/` is stubbed and runs locally; it never reaches api.daily.co
(`DAILY_ENABLED` defaults false, `@daily_on` uses a fake key, provisioning is
monkeypatched — `video/tests/test_views.py:13`). It stays local. Missing cases,
all of which produce "I registered and I can't get in" on the day:

- pending-but-unpaid registration → denied
- cancelled / refunded registration → denied
- comped registration → allowed
- `seminar_access_suspended` profile
- anonymous on the **event-owned-room** path → redirect to login, not 403
  (covered today only for the seminar/workgroup path)
- the spotlight start-off matrix through the view (owner vs. attendee)
- event-page Join-button gating across live / not-live / host
- property reconciliation against an existing room (regression test for R1)

### 1.7 Walk the guest funnel

Drive signup → email verification (task #471, POST-gated) → registration →
payment end to end in a browser as a fresh account. Longest untested chain, and
the one strangers will be on.

## Phase 2 — live dress rehearsal

**Venue.** A throwaway prod event mirroring Masochism's config, titled so nobody
mistakes it for the real thing, its session scheduled *at* the rehearsal time so
`is_live()` is genuinely true. A different slug means a different room, so the
rehearsal cannot disturb the real one. Deleted afterward — **registrations
first**, both FKs are `PROTECT`.

**Cast**, ~45 minutes:

| Role | Who | Tests |
|---|---|---|
| Speaker | Stephanie, her real machine / network / slides | screen share, owner controls, the highest-variance component |
| Host | Rico | pre-open, moderation, recording start/stop |
| Member attendee | internal | paid-registration join path |
| Guest attendee | internal, brand-new account | signup → verify → register → join |
| Latecomer | internal, joins 20 min in | mid-meeting join, spotlight still applies |
| Disruptor | internal | host mute/remove, rejoin after force-refresh |

**Beats.** T-15 pre-open → join at T-0 → confirm everyone lands muted and
camera-off → slides shared and legible → chat Q&A → hand-raise → host mutes the
disruptor → start and stop a recording → force-refresh and rejoin → leave
returns to the event page.

**Browsers.** Chrome, Safari on macOS **and** iOS (historically Daily's weak
spot), one Android.

**Observation.** Claude is not in the room; instrumentation is prod-side
(presence API, container logs, DB rows) while the cast fills a one-page
checklist.

## Deliverables

- `manage.py event_video_preflight` (read-only, `--provision` opt-in)
- the R1–R4 fixes, deployed
- the phase 1.6 tests
- `docs/event-video-rehearsal.md` — runbook, per-role scripts, checklist

## Pass criteria

Every checklist line green, or a logged issue with a fix landed and re-verified.
Anything unresolved is written into task #475 as a known risk with a stated
mitigation — not quietly dropped.
