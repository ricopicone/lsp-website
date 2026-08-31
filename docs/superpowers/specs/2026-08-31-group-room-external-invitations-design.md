# Inviting someone into a group's meeting room

Task #694. Design date 2026-08-31.

## The ask

> Add external invitations for all group meeting rooms. Use a very similar if
> not identical approach that we used for personal meeting rooms. External
> invitations can be managed by leaders of the group (e.g., president of the
> board on the board, faculty of a seminar, etc.). We have a leader definition
> already.

## What exists

Every group room on the site admits exactly one population: its own. A
`Workgroup` room is gated by `services.can_enter` → `Workgroup.is_member`
(faculty plus the current term's paid and comped registrants for an offering,
the stored roster for a cartel or committee); a one-off event's room is gated by
`can_enter_event` → a paid/comped registration or `can_edit_event`. There is no
third answer. A discussant a committee wants to hear from once, an outside
speaker's interpreter, a candidate the Board is meeting — none of them has a way
in short of being put on a roster, which also hands them the group's Parlêtre
channel, its files and its minutes.

Task #687 built the missing mechanism for a *different* room. A member's
`PersonalRoom` carries `RoomInvitation` rows in two kinds — an account-bound one
naming a person who signs in as themselves, and a `token` in a `/meet/g/<token>/`
URL for someone with no account — behind an invariant that makes a leaked link
harmless: nobody but the owner is in the room unless the owner is in it. This
task carries that mechanism across to the group rooms, with the invariant
restated for a room that has no single owner.

Deliberately **out of scope: Parlêtre channel video rooms.** A channel room's
access follows `channel_visible`, and a private channel is private even from
staff (task #360). That promise is a separate thing and is not weakened here.

## The model: an invitation names its target

`RoomInvitation` becomes polymorphic over three targets, mirroring the style
`DailyRoom` already uses one file up:

* `personal_room` — the field currently called `room`, renamed;
* `workgroup` — every group room (cartel, committee, working group, seminar,
  reading group);
* `event` — a one-off event that owns its own room (special event, Day of
  Assembly, Working Day, Scholarly Seminar).

Exactly one is set, enforced by a `video_invitation_exactly_one_target` check
constraint replacing the two-way `video_invitation_exactly_one_kind`, which
keeps its own job of separating the account-bound kind from the guest kind. Every
existing row is personal, so the new constraint holds the moment the rename
lands; no data migration, no backfill.

Rejected: **pointing the invitation at `DailyRoom`.** One FK and no constraint,
but rooms are provisioned lazily by a Daily API call, so issuing an invitation
would force provisioning and fail whenever Daily is off or unreachable — and a
personal invitation today legitimately exists before any room does. An invitation
is a decision about a person and a group, not a reference to a provisioned
provider resource.

Rejected: **a second `GroupRoomInvitation` model.** It leaves the shipped path
untouched at the price of a second copy of one state machine — `live()`, revoke,
touch, `is_guest`, token minting — and two implementations of one state machine
drift. That is the #532 and #568 lesson, and the reason task #627 gave
`cancel()` a keyword rather than writing a second cancel.

One field is added: **`invited_by`** (nullable FK to `accounts.User`,
`SET_NULL`). A personal room's inviter was implied by its owner. A group has
several leads, so the row is the only place recording which of them opened the
door; it supplies the guest email's `Reply-To`, the "invited by" line on the
list, and the audit trail.

### `expires_at` by target

| target | account-bound | guest link |
|---|---|---|
| personal room | never expires | 30 days (`DEFAULT_TTL_DAYS`) |
| workgroup / event | never expires | never expires |

A group's guest link lasts until it is revoked. That is safe here in a way it
would not be on its own: the presence gate below means a link alone never opens
an empty room, and unlike a personal room's invitations, a group's live list sits
on the group's own Meet tab where every lead can see and revoke it. A flat TTL
was considered and rejected for the reason `events.speaker_invitations` already
rejected one — a 30-day link issued in July for a September event lapses in
August, and a lapse is discovered at the worst possible moment.

## The invariant

> **A guest is never the first one in the room.**

The counterpart to #687's "nobody but the owner is in a personal room unless the
owner is in it", restated for a room with no single owner. It binds every
entrant who is not already admitted by `can_enter` — an invited account holder
and an anonymous guest alike. A forwarded or leaked link therefore reaches a
doorstep saying the meeting has not started, never an empty room.

"Someone is in it" is `services.room_participant_count(...) > 0` read from the
**existing** `DailyRoom` row, never through `ensure_room`. Going through
`ensure_room` would provision a Daily room for a group that has never met, and
would turn a doorstep GET into a write.

Only members and previously-admitted guests can be in a group's room, so the
count cannot be manufactured: the first guest to arrive finds zero and waits.
Members leaving while guests remain is accepted, exactly as it is for a personal
room — the check is made when the token is minted, and Daily does not eject at
token expiry (`eject_at_token_exp` defaults false), so a brief drop by the
member running the meeting does not throw everyone out.

Presence is read from the account-wide `GET /presence` map `services` already
caches for ~20 seconds, so a guest may wait up to about half a minute past the
first member's arrival. The doorstep polls; priming the cache when a member's
token is minted was rejected in #687 for the reason that still applies — they may
never clear the prejoin screen, and a doorstep claiming the meeting has started
when nobody is there is worse than one that lags.

An invitation deliberately **bypasses registration and roster membership**. That
is the lead's decision to make (architecture §4.1, space for the singular), and
it is why the live list is visible and revocable on the tab where the room lives.

## Who may invite

`services.is_owner(target_owner, user)` — the site's existing single definition
of "runs this meeting", already what grants the Daily moderator flag and the
Record button. For a workgroup that is `is_workgroup_lead` (including the
derived President and Vice-President on the Board and the Meeting of Analysts,
task #480) plus `can_edit_event` on the group's primary event; for a one-off
event it is `can_edit_event`.

For a **personal** target `may_invite` stays what it has always been: the room's
own member, nobody else. Unifying the revoke endpoint across the three targets
must not widen that, and a test pins it.

It also admits the Web Coordinator and Web Developer through
`is_site_technical`. That grants them nothing new — they can already enter and
moderate every group room so they can help when an event goes wrong — and it is
the opposite of the exclusion `can_enter_personal` makes, which exists because a
*private* room is private even from staff. Reusing `is_owner` rather than
writing a narrower leads-only predicate keeps one answer to "who runs this
meeting" instead of two that must be kept in step.

## The target adapter

Everything that differs between the three targets is answered by one small
adapter in a new `video/invitations.py`, rather than by `if`/`elif` chains at
each call site — the #532 lesson about a fact every surface re-derives. It
answers:

* the FK kwarg to build a row with (`{"workgroup": wg}` / `{"event": ev}` /
  `{"personal_room": pr}`);
* its live-invitation queryset;
* the name shown to an invitee ("the Board", "Working with Masochism");
* **who counts as present** — the owner for a personal room, anyone at all for a
  group;
* `may_invite(user)`;
* the URL an account-bound invitee follows once signed in;
* which users to leave out of the member picker. For a personal room that is
  its owner. For a group it is everyone the room already admits, since inviting
  them would be a no-op — read from `Workgroup.participants()`, **not**
  `active_members()`, which returns stored rows only and so cannot see a
  seminar's registrants or a committee's ex-officio officers
  (`active-members-vs-participants`).

One rule inside it is load-bearing: an **offering** event (seminar, reading
group, cartel) meets in its *workgroup's* room, so its target resolves through
`services.room_owner_for_event`. Without that, a seminar's page would mint
`event`-target invitations against a room the event does not own, and they would
admit nobody. Only a one-off event gets an `event` target.

`services_personal.py` keeps the personal invariant and the office-hours logic
and delegates the shared parts. `InvitationForm` moves from
`forms_personal.py` to `video/forms_invitations.py`, parameterized by a target
rather than by `room=`.

## Getting in

Four entrances, all reaching the same check.

**A member.** `/groups/<slug>/room/` and `/events/<slug>/room/`, admitted by
`services.can_enter`. No doorstep. Nothing changes — and because the invitation
fallback runs only *after* `can_enter` refuses, someone who is both invited and a
member is admitted as a member, never held at a doorstep.

**An account-bound invitee.** The *same* URLs, so the bell notification and the
email point at the ordinary room link and no second address has to be explained.
`_render_room` today raises `PermissionDenied` the moment `can_enter` refuses; it
gains one fallback — look for a live invitation for this user on this target, and
if there is one, apply the presence gate and render either the room or the
waiting doorstep.

**An anonymous guest.** `/meet/g/<token>/`, the existing route and URL name kept
unchanged so links already mailed keep working, with the view dispatching on the
invitation's target. GET renders and mints nothing: email link-scanners pre-click
links on exactly the addresses this gets mailed to
(`auth-email-scanner-and-reset-gotchas`), and a GET that minted a Daily token
would put a scanner in the room. The display name typed on the POST rides into
the Daily token, so a lead sees a person in the People panel rather than a row of
"Guest".

**The poll.** `{"live": true|false}`, scoped to the **invitation** rather than to
the room: `/meet/g/<token>/presence/` for a guest, `/video/invitations/<pk>/presence/`
for a signed-in invitee. Only someone holding an invitation may ask whether a
group's meeting has started, so knowing a workgroup slug does not let anyone
probe a committee's live state.

Three consequences worth pinning by test:

* a guest is **never** `is_owner`, on any target — no Record button, no
  moderator controls;
* a guest at a one-off event still goes through `services.spotlight_start_off`
  and `services.token_exp_for`, so at a `speaker_spotlight` event they join muted
  and camera-off like every other attendee, and their token covers the event's
  joinable window rather than the flat three-hour TTL;
* group rooms keep `enable_knocking` false (`_desired_properties` reads
  `waiting_room` off the owner, which only a `PersonalRoom` has). The doorstep is
  the gate; a group room gains no Daily lobby.

## Surfaces

The invite form and the live-invitation list — member picker with its live
filter, the free-text "anyone else" box, the copy-link button and Revoke — move
out of `formation/_tab_room.html` into one partial,
`video/_invitations_panel.html`, driven by a context dict. The My LSP room tab
then renders the same partial it renders today. Touching shipped #687 markup is
the lesser cost: two copies of one form's validation and copy drift.

It renders in three places, always gated by `may_invite`:

* **the Workspace Meet tab**, under the existing Meeting room card, with context
  added in the `active == "meet"` branch of `workgroups/views.py`, which already
  computes membership and presence;
* **a one-off event's page**, in the faculty block. `events/_faculty_tools.html`
  is included by *both* the event page and the Workspace roster tab, so the panel
  is **context-gated, not template-gated**: `event_detail` supplies it only when
  `room_owner_for_event(event)` is the event itself, and the roster tab never
  supplies it — so an offering never grows a second, wrong invite form beside its
  workgroup's;
* **My LSP → Meeting room**, unchanged in behaviour.

Endpoints. Invite is per-target, because the URL is what names the target:
`/groups/<slug>/room/invite/`, `/events/<slug>/room/invite/`, and the existing
`/video/my-room/invite/`. Revoke collapses to **one** endpoint for all three,
`/video/invitations/<pk>/revoke/`, authorized by `may_invite`; the personal-only
`video:room_invite_revoke` is absorbed into it.

## Telling the person

`Category.MEETING_ROOM_INVITE` is reused — the same act, the same audience, the
same preference the member has already set.

An account holder gets the ordinary bell and preference-gated email through
`notify`, with the inviter as actor and the group as subject ("Rico Picone
invited you to a meeting of the Board"), landing on the ordinary room URL. A
guest has no account and so no preferences, and is emailed the token link
directly, `Reply-To` the inviter, only when an address was given — the link is
always shown to the lead as well, since handing it over in an existing thread is
often what they want. The group email carries no expiry sentence, because
nothing expires.

The doorstep and the email name the group and say the guest can join once the
meeting starts. #687's "please do not use it for clinical work with analysands"
line is **not** carried over: it exists because a personal room belongs to one
clinician, and a committee's room is not at that risk.

The panel is leads-only, so ordinary members do not see the invitation list. A
guest is disclosed by being named in the People panel, under the name they typed.

## Testing

* the three-way target constraint, and that the kind constraint still holds;
* `may_invite` gating the panel, the invite POST and revoke — a plain member of
  the group refused, a lead admitted, a site-technical role admitted;
* the presence gate both ways with `presence_map` patched: doorstep at 200 with
  `waiting` when the room is empty, the room when it is occupied;
* a guest GET making no Daily call at all;
* an offering event's target resolving to its **workgroup**, not to the event;
* revoked invitations refused at every entrance, and a personal guest link still
  expiring at 30 days;
* the presence endpoints refusing anyone not holding the invitation;
* a guest never minting an owner token;
* a regression pass that personal rooms behave exactly as #687 shipped them.

No migration beyond the field rename, the two new FKs, `invited_by` and the
constraint swap. No backfill, no flag beyond the `DAILY_ENABLED` one the video
app already has.
