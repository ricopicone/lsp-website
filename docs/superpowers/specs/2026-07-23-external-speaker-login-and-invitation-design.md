# External speakers: login + invitation (task #463)

**Status:** design approved 2026-07-23. Scope: Parts 1 + 2. Part 3 (speaker
spotlight) is deferred to a follow-up (sketched at the end).

## Problem

Special events can have external presenters (e.g. Derek Hook) who are not LSP
members. Today an external presenter is an `events.Speaker` row — display-only,
**no login**. The recent presenter work (task #463) gives *internal* presenters
(`Event.member_speakers`, LSP `User`s) the faculty view and, crucially, access
to the integrated video meeting room, because `Event.is_presenter()` →
`can_edit_event()` → `can_enter_event()`/`is_owner()` all key off a `User`.

An external `Speaker` has no `User`, so it gets none of that: Derek can't log
in, can't see the join affordance, can't enter the room. We need to (1) let an
external speaker have a login that confers the same per-event presenter access,
and (2) give the Programming Committee a clean way to invite them — provision an
account, email them, and explain how joining works — without silent automation.

## Constraints / grounding facts

- **Two speaker models exist and stay distinct.** `events.Speaker` (external,
  external identity: name/bio/affiliation/headshot/`public`/`email`) attached to
  an event via the `Event.speakers` M2M; `Event.member_speakers` (LSP `User`s).
  Do not merge them — external speakers keep their affiliation identity and
  display.
- **Password reset skips unusable-password accounts** (memory
  `auth-email-scanner-and-reset-gotchas`). A freshly-provisioned invited user
  has an unusable password, so Django's reset flow will silently drop them. The
  invitation therefore needs its own token, not the reset flow.
- **Directory inclusion** = `Profile.role in DIRECTORY_ROLES AND public=True AND
  standing not in NON_MEMBER_STANDINGS` (`accounts.views._directory_qs`).
  `Profile.role` defaults to `EXTERNAL` ("Auditor"), which is **not** a directory
  role, so an invited external speaker stays off the directory by default. No
  persona-style filtering needed. They also join no workgroup, so no roster leak.
- **do-not-over-automate.** Every automated path keeps human discretion. The
  invitation is prepared automatically but a human confirms before anything
  sends (per Rico, 2026-07-23).
- **Email From/name + templates.** Follow existing patterns: friendly From via
  `core.email`, editable message text like the referral `MessageTemplate`s.

## Part 1 — External speaker login + presenter access

### Data model
- Add `Speaker.user = OneToOneField(User, null=True, blank=True,
  on_delete=SET_NULL, related_name="external_speaker")`. Nullable so existing
  display-only speakers are unaffected. One login per external-speaker identity.
- No change to `member_speakers` or `Event.speakers`.

### Access predicate
- Extend `Event.is_presenter(user)` so, on a non-offering event, it is true when
  **either** the user is in `member_speakers` **or** the event has a linked
  external speaker for that user:
  `self.speakers.filter(user=user).exists()`.
- Nothing else changes: `can_edit_event`, `can_enter_event`, `is_owner`, the
  faculty-view toggle, the access-details block, and the `_location.html` room
  affordance already flow through `is_presenter`/`can_edit_event`, so a linked
  external speaker gets exactly what an internal presenter gets — faculty view,
  access details, and moderator-level entry to the meeting room — scoped to that
  one event.

### Account shape for an invited external speaker
- `role = EXTERNAL` (default), `public = False`, `is_faculty = False`.
- Off the directory (role gate) and off all rosters (no workgroup membership).
- Name on the `User` mirrors the `Speaker.name` for the meeting-room display
  name; the `Speaker` row remains the source of the public bio/affiliation.

## Part 2 — Invitation flow (prepare-on-add, confirm-before-send)

### Where external speakers come from (entry points)
- **Proposal approval** already mints external `Speaker` rows (name / bio /
  affiliation / email) from the proposal's `ProposalSpeaker`s and attaches them
  via `Event.speakers` (`EventProposal._attach_speakers`). So a properly-proposed
  special event arrives with its external speakers (and their emails) in place.
- **Ad hoc / legacy** (e.g. Working with Masochism, which predates the proposal
  pipeline): external speakers are added in Django admin (the `Event.speakers`
  M2M / speaker inline). We do **not** build a new PC-facing "add external
  speaker" form in this scope — adding stays in Django admin / the proposal flow.

### Trigger + UX
- The **invitation lives on the PC/staff-gated event edit page**
  (`events:edit`, already gated by `can_edit_event`). It lists the event's
  external speakers; each one **with an email** that has no active login/invite
  shows a highlighted **"Ready to invite"** panel with a **pre-filled, editable
  invitation** and an explicit **Confirm & send** button.
- This is the "prepare automatically, confirm before send" shape: the prepared
  invitation appears on its own as soon as an emailed external speaker is on the
  event — nothing sends until the PC presses Confirm & send, and there is no
  separate easily-forgotten button to hunt for.
- If a speaker has no email, no invitation panel is offered (nothing to send to).
- Once invited, the panel shows status (invited / accepted); **resend** is
  allowed and refreshes the token.

### Token
- New model `events.SpeakerInvitation` (mirrors `EmailChangeRequest` /
  `MagicLoginLink` shape):
  - `speaker` (FK), `user` (FK, the provisioned/linked login),
  - `token` (single-use, URL-safe, stored hashed),
  - `created_at`, `expires_at` (generous — through the event date, minimum e.g.
    30 days), `used_at` (null until consumed).
- Works for unusable-password accounts (it is our own token, not Django reset),
  side-stepping the reset gotcha.

### On confirm
1. Provision-or-link the `User`: if a `User` with that email exists, link it to
   the `Speaker`; else create one (`role=EXTERNAL`, `public=False`, unusable
   password) and link it.
2. Create a `SpeakerInvitation` token.
3. Send the invitation email (editable template).

### Invitation email
- Editable `MessageTemplate`-style text (seeded with sensible default wording;
  do not hardcode). Explains, in member-facing copy style (commas, not em
  dashes):
  - a one-click link to **set your password / activate your account**,
  - then how joining works: you'll open the meeting room **right on the event
    page** — there's no separate meeting link; a Join button appears there when
    the event begins (the same explainer speakers see on the page).
- Landing: token link → "set your password" page → on success, log them in and
  redirect to the event page (`events:detail`).
- Token link is POST-gated on consumption where a set-password form is involved,
  to survive email link-scanners (memory `auth-email-scanner-and-reset-gotchas`).

### Permissions
- Only PC / staff (`_is_pc_or_staff`) can prepare/confirm/send an invitation.
- Anonymous and non-PC users cannot trigger it (404, matching the other PC-admin
  actions).

## Testing

Part 1:
- A `Speaker` linked to a `User` on a special event → `is_presenter`,
  `can_edit_event`, `can_enter_event`, `is_owner` all true for that user; the
  event page shows the faculty view, access details, and the room affordance.
- The linked external-speaker `User` does **not** appear in `_directory_qs` /
  the directory, and is on no workgroup roster.
- A linked external speaker on an *offering* (seminar) gets nothing (mirrors the
  member-speaker guard — offerings have real faculty).

Part 2:
- Adding a speaker with an email surfaces the confirm step; no email sends on add.
- Confirm provisions-or-links a `User`, creates a token, sends one email.
- Confirm with an existing-email `User` links rather than duplicates.
- Token link lands on set-password, sets a usable password, logs in, redirects to
  the event; the user can then reach the room.
- Expired / already-used / malformed token rejected.
- No email → no invitation offered.
- Anonymous and non-PC cannot prepare/confirm/send (404).

## Out of scope (Part 3, deferred follow-up)

Speaker spotlight (soft, per-event, off by default): `Event.speaker_spotlight`
boolean; when on, non-owner Daily meeting tokens are minted with
`start_audio_off` + `start_video_off` so only the speaker/hosts come in live and
are the visual focus, while attendees can still unmute (soft) and hosts can mute.
Uses the existing `mint_token` path. Independent of Parts 1–2; ship separately.
