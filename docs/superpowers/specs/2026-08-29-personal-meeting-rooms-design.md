# A private meeting room for every member

Task #687. Design date 2026-08-29.

## The ask

> The new website has a built-in web video conferencing tool that might suit you
> well. Recently, Diana requested an "office hours" functionality so faculty can
> meet with seminar members outside of the regular seminar "room." I can make it
> so each member of the school has a private room to which they can invite
> others. I think this would solve both issues, "office hours," and interviews.

Three things, decided together (Rico, 2026-08-29) because they share one room and
would otherwise build its surfaces twice: a personal room, its invitations, and
faculty office hours.

## What exists

`video/` already provisions persistent Daily rooms lazily and gates them
server-side. Three owners today, mutually exclusive by DB constraint
(`video_room_exactly_one_owner`): a `Workgroup` (a group's standing room), a
Parlêtre `Channel` (board video channels), and a one-off `Event` (task #463).
`services.ensure_room` reconciles the room's full property set against Daily on
every join (task #475), so a new property reaches existing rooms with no
backfill.

Two facts shape everything below.

**Every room path is `@login_required` and mints a per-user Daily token.** The
raw Daily URL is useless without one, which is why `views.py` says emailing a
gated room URL is safe. The school's existing answer for an outsider who needs
into a room is not an anonymous link but `events/speaker_invitations.py`:
provision a login, mint an invitation token, email it. A tokenless entry path is
therefore new ground, and is the part of this feature that needs the most care.

**`services.py`'s owner handling is duck-typed, not `isinstance`-driven, in the
places that matter.** `_desired_properties` reads `owner.recording_mode` through
`getattr`; `_room_name` reads `owner.slug`. Anything that supplies those two
attributes can own a room without touching that logic.

## The model: `PersonalRoom` owns the `DailyRoom`

Rejected: **a fourth `DailyRoom` owner column (`user`)**, with the member's
settings on `Profile`. It is the smallest migration but the worst placement: five
polymorphic sites in `services.py` grow a fourth branch, and four more fields
land on a `Profile` that is already long.

Rejected: **a one-member `Workgroup` per member.** The project's rule is "add a
group feature to `Workgroup` first," and this would inherit the room, roster,
recording mode and Meet tab free. But it would also mint a Parlêtre channel per
member, list eighty personal workgroups under `/groups/`, and carry a roster
whose meaning — *membership* — is wrong for an hour-long interview guest. The
rule is about group features; a personal room is the case it does not fit.

`video.PersonalRoom` is the room's owner and satisfies the duck-typed protocol,
so `_room_name` and `_desired_properties` need no new branch:

```
user            OneToOne(User)          the member
slug            CharField unique        opaque, e.g. "pr-9f3c…"; the room name and the site URL
recording_mode  CharField               "off" (default) | "on_demand"
office_hours    CharField               "off" (default) | "posted" | "appointment"
hours_note      CharField(200)          free text, e.g. "Thursdays 3-4pm Pacific"
created_at
```

`DailyRoom` gains a nullable `personal_room` OneToOne and the exactly-one-owner
constraint becomes four-way.

**The slug is opaque, not the member's directory slug.** Daily's room name rides
in the iframe URL, where a guest can read it; there is no reason a one-off guest
should learn a member's directory handle from the page furniture.

**No `enabled` flag.** A member with no invitations and office hours off has a
room only they can enter, which is indistinguishable from not having one — an
explicit switch would add a state (disabled room, live invitations) whose
behaviour someone would then have to define. Turning office hours off and
revoking invitations is the same thing, said in terms that already exist.

Rooms are created lazily, on the member's first visit to their own room page.
Nothing is provisioned for the eighty existing members, and there is no backfill.

## Who has one

`accounts.permissions.is_lsp_member` — the one definition, as everywhere else.
Auditors, Students, Prospective Applicants and external accounts do not get a
room, which is what "each member (not non-member users)" asks for. They can still
be *invited* into one.

## The invariant

**Nobody but the owner is in a personal room unless the owner is in it.**

This is the safety property the whole design leans on, and it holds for every
entrant — an invited member, an invited account-holder, an anonymous guest, a
student walking in during office hours. It is checked when the token is minted;
Daily does not eject at token expiry, so someone already in the room stays if the
owner's connection drops, exactly as a knock-to-enter lobby behaves.

Presence is already implemented (`services.presence_map`, a single account-wide
`GET /presence` cached 20s). The cost is that a host who joined seconds ago may
not register yet, so the doorstep polls; worst case a guest waits about half a
minute past the host's arrival. Rejected: priming the cache when we mint the
owner's token — they may never clear the prejoin screen, and a doorstep that
says "your host is here" when nobody is is worse than one that lags.

Rejected: **a scheduled window on each invitation** ("expires after the meeting
time"). It reads the ask literally but needs a scheduling form, an
upcoming-meetings list, and a decision about a meeting that starts late; and a
link that is live for its window is live whether or not the host ever arrives.
Presence answers the same question with data we already have.

Rejected: **Daily's `enable_knocking`.** It is the native shape of this, but it
gates on the *room URL* rather than on anything we issue, making that URL a
permanent bearer secret and the knock queue a thing anyone holding it can spam.
Every other room here is gated server-side before a token exists; this one should
be too.

### The site-technical roles are excluded

`services.is_site_technical` (Web Coordinator, Web Developer) enters and
moderates every meeting on the site so someone can help when an event goes wrong.
A personal room is the exception, for the reason `can_enter_channel` already
excludes them from Parlêtre private channels: a private channel is private even
from staff (task #360). Widening entry here would break the same promise, and the
promise is the feature. Stated in `can_enter_personal` with that reference, so a
later reader does not "fix" the omission.

## Getting in

One `RoomInvitation` model, two kinds, mirroring the exactly-one-owner constraint
style already in this app:

```
room            FK(PersonalRoom)
invited_user    FK(User, null)       internal: an account, member or not
token           CharField(unique, null)  guest: the secret in the URL
guest_name      CharField            guest: prefills the display name
guest_email     EmailField(blank)    guest: optional, for sending the link
note            CharField(blank)     shown on the doorstep
created_at / expires_at / revoked_at / last_used_at
```

A check constraint requires exactly one of `invited_user` / `token`. Both kinds
expire (default 30 days) and both are revocable; an invitation is reusable within
its window, since office hours and a rescheduled interview both want the same
link twice, and revocation is the way to end one early.

**Internal.** The member picks accounts — members and non-members alike, so an
applicant being interviewed is reachable by name rather than by secret link — and
each gets a bell row and an email carrying a link to `/meet/<room-slug>/`. They
sign in as themselves and are subject to the invariant.

**Guest.** For someone with no account. The member creates the invitation with a
name, optionally an email to send it to, and gets back a secret URL,
`/meet/g/<token>/`. That page is the doorstep: it names who invited them, states
that this is a private meeting room, carries the use policy, prefills their
display name, and shows either a Join button or "…has not started the meeting
yet", re-checking every 15 seconds. Joining is a POST which mints a non-owner
Daily token carrying the name they gave, so the member sees a person in the
People panel rather than "Guest".

**GET does nothing and consumes nothing.** Email link-scanners pre-click links on
exactly the corporate addresses this will be mailed to
(`auth-email-scanner-and-reset-gotchas`); the invitation is deliberately not
single-use, and the token mint is behind the POST.

## Office hours

Three modes on `PersonalRoom`, default **off**, so nothing appears anywhere until
a faculty member opts in:

- **off** — not advertised; invitation-only entry. The default for everyone.
- **posted** — `hours_note` is advertised, and **LSP members may walk in while
  the owner is in the room**.
- **appointment** — advertised as by-appointment with the note explaining how to
  arrange one; **no walk-in entry.** The meeting itself happens through an
  invitation.

The mode says whether the door is open, which is what makes "by appointment"
mean something rather than being a label on an open door.

Walk-in entry is `is_lsp_member`, not "the rosters of offerings you lead." A
second audience concept would have to be defined, stored and explained, and the
presence gate already puts the faculty member in the room with the People panel
in front of them. The member controls the door by controlling the mode.

That leaves one seam, and it is handled rather than left: an offering's roster
can include guests (task #566 — a registered non-member), so on the Workspace the
hours are shown to the whole roster but the **Join button is rendered only to
members**. A guest reads the note and writes to the faculty member, which is what
the note is for. A button that leads to a refusal is worse than no button — the
rule task #566 settled for the Register CTA.

The setting is open to any member, not gated to `is_faculty`, though the ask
names faculty. The Workspace surface is already faculty-shaped, since it renders
only for `offering_leads`; the directory surface costs nothing to leave open, and
an analyst who wants to post hours is not a case worth a permission check to
forbid. It is off by default for everyone.

**Advertised in two places** (Rico, 2026-08-29), both already gated:

- The Workspace of each offering the member leads, to that offering's roster —
  Diana's actual ask, students in the class. The audience is
  `events.permissions.offering_leads`, so a reading group's conveners are
  included; `faculty_members()` would have missed them, which is the defect
  task #564 had to fix in the approval notice.
- Their directory profile, to signed-in LSP members only, the way
  `_availability_rows` already returns `None` for anonymous viewers. Not public:
  a public page would advertise a private room and a weekly schedule to the open
  internet.

`hours_note` is free text, not a structured recurrence. "Thursdays 3-4pm Pacific"
and "alternate Tuesdays after seminar, or write to me" are both things a faculty
member will want to say, and a scheduler that cannot express the second is worse
than a sentence that expresses both. No calendar feed, no booking.

## A waiting room, off by default

Added after review (Rico, 2026-08-29). Presence answers *has the meeting
started*; it does not answer *is the host ready for me now*. During office hours
those come apart — the host is in the room, mid-conversation with someone else,
and the next arrival should wait. `PersonalRoom.waiting_room` holds arrivals on
Daily's knock screen until the host admits them one at a time.

**Both halves are required, and this is the part that is easy to get wrong.**
The room property `enable_knocking` alone is inert here: a participant holding a
meeting token *bypasses* the knock screen by default, and every join on this site
is token-minted, so nobody would ever have knocked. The meeting token must also
carry `knocking: true`. The owner's token never does — they are the one
admitting. `_desired_properties` reads `enable_knocking` off the owner
(`getattr(owner, "waiting_room", False)`), so every group room keeps today's
`False` and only a personal room can opt in; `ensure_room` reconciles on the next
join, so toggling it needs no backfill.

**Verified against the live Daily API on prod (2026-08-29)**, which is worth
recording because the check itself went wrong first. Daily *abbreviates* meeting
token claims in the JWT — `knocking` becomes `k`, `enable_prejoin_ui` becomes
`epui`, `start_video_off` becomes `vo` — so a script looking for a claim named
`knocking` finds nothing and reports a no-op on a feature that works. The real
signal is the opposite one: Daily **rejects** an unknown token property with
HTTP 400 `invalid property name`, confirmed by probing `enable_knocking`,
`require_knocking`, `knock` and `auto_admit`, all four of which 400. So a token
that mints at all carries every property you sent, and a missing claim means you
are looking for the wrong name. Measured: a baseline token claims
`['d','iat','o','r','u']`; adding `knocking` adds `k`; the owner's token does
not carry it.

Default off, because an invitation is already a decision about a person and most
meetings should not make it twice. It composes with the invariant rather than
replacing it: presence still gates the door, and knocking adds a second,
per-person approval behind it.

## Recording

`recording_mode` defaults to **`"off"`**, against the `"on_demand"` default every
other room kind carries — this room holds application interviews and office
hours, and a Record button does not belong in one by default. The member turns it
on for their own room, which is the adjustable setting the ask names. The
existing `_desired_properties` already translates the field into Daily's
`enable_recording`, and `ensure_room` reconciles it on the next join, so
flipping the setting needs no extra plumbing.

Two things must change in `video/models.py` or a personal recording is broken on
arrival.

`Recording._can_host` resolves through the event, then the workgroup, then falls
back to `services.is_site_technical`. A personal-room recording has neither, so
today the member could neither manage nor **watch their own recording** while the
Web Coordinator could. It learns the personal case: the room's member is its
host.

And a personal recording is **owner-only, with no availability form.** The six
visibility settings are built on two dimensions, one of which is roster
membership, and a personal room has no roster — `ROSTER` and `ROSTER_MEMBERS`
would silently mean "nobody". Rather than offer three of six settings on that
page, the availability controls are hidden for a personal recording and it stays
at the `OWNERS` default. Sharing one means downloading it. Retention is
unchanged: the ordinary one-year sweep, with `keep` available.

## Surfaces

- **My LSP → "Meeting room"** (`?tab=room`), gated on `is_lsp_member` in
  `formation/tabs.py`. The member joins their room, copies its link, manages
  invitations, sets recording and office hours there. The avatar menu picks the
  tab up for free: it renders `my_lsp_tabs`, the same list the hub uses.
- **`/video/my-room/`** — the owner's embedded room, reusing `video/room.html`.
- **`/meet/<room-slug>/`** — an invited signed-in user, or an LSP member during
  posted office hours.
- **`/meet/g/<token>/`** — the guest doorstep.
- **Workspace overview** and **directory profile** — the office-hours sections
  above.

**Parlêtre gets nothing, for now.** The natural surface is a "start a call"
action on a private chat, and private chats are hard off in production
(`PARLETRE_PRIVATE_CHATS_ENABLED` defaults false; task #360), so the work would
ship invisible. Revisit when private chats come back.

## Saying what the room is

Two pieces of standing copy, in the member-facing register the school uses
(commas, not em dashes; say what, not why):

- **It is not a seminar room.** The room page, the invitation email and the guest
  doorstep all name it "your private meeting room" and say it is separate from
  the meeting rooms for seminars and events, so nobody joins their class here.
- **What it is for.** "This room is for the work of the School, for example
  office hours, interviews, and committee conversations. Please do not use it for
  clinical work with analysands." On the member's room page, where the person who
  decides what to use it for will read it.

## Testing

- The invariant, directly: an invited user, a guest token, and an office-hours
  walk-in are each refused while the owner is absent and admitted while present.
- The site-technical roles are refused entry to a personal room (the promise this
  feature makes, and the one a later reader is most likely to "fix").
- A non-member gets no room; an invited non-member can still enter one.
- `appointment` advertises but does not admit; `off` does neither.
- A guest GET mints nothing; the POST mints a token carrying the given name.
- A revoked or expired invitation is refused in both kinds.
- `Recording._can_host` is the personal room's member, and is not the Web
  Coordinator by way of the old fallback.
- The exactly-one-owner constraints on both new models.

No migration of existing data, no backfill, no feature flag beyond the
`DAILY_ENABLED` one the video app already has.
