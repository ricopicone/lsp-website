# PC-admin direct create for special events

*Task #421 follow-on. Design date: 2026-07-12.*

## Problem

A Program Committee member has no direct way to create a **special event**
from the PC admin. The Programs-tab "+ New event" is hard-restricted to
annual-program types (seminar / reading group / cartel) and force-attaches a
`Program`. The only in-app path to a special event is the member-facing
**proposal** flow: fill `propose_event` → PC approves it in the Proposals tab.
A PC member therefore has to propose-to-themselves, then approve — or drop to
Django admin.

Two related gaps in the special-event lifecycle:

1. **No direct create** in the PC admin (above).
2. **No in-app draft control.** For a special event, `Event.published` is the
   live/draft flag directly (`is_public_now` returns `self.published`; unlike
   annual-program events, which cascade from `Program.is_public_now`). Today a
   special event only becomes a draft by leaving its date TBD (`approve()` mints
   `published=(has_real_date)`), which conflates "no date yet" with "not ready
   to announce." And there is **no in-app way to publish a draft special event
   later** — only Django admin.

There is deliberately **no per-event scheduled publish date**; that mechanism
(`publish_date` + auto-publish timer) lives only on `Program`. Special events go
live on create (or via an explicit publish action) — no scheduling.

## Goal

1. A PC-only "+ New special event" create action that mints a fully wired
   special event, with an explicit **Create & publish** vs **Save as draft**
   choice.
2. A discoverable in-app home for special events with a **Publish / Unpublish**
   control, so a draft can be taken live (or pulled back) without Django admin.

### Non-goals

- Other standalone types (Day of Assembly, Working Day, Scholarly Seminar)
  stay in Django admin — rare and institutional.
- Full in-app *editing* of a special event's access_info / pricing tiers is
  unchanged: `events:edit` (limited content fields) or Django admin.
- Per-event scheduled publish date — not building it.
- The draft/publish choice is **PC-admin only**; the member propose flow is
  untouched (it already has "Save for later" for a proposer's own drafts, and
  publishing is the PC's call).

## Approach — reuse the proposal → approve pipeline

`EventProposal.approve()` already encapsulates the non-trivial minting of a
special event: builds the **price tier** from the proposed fee, turns the
date/time into the event's first **Session**, wires internal speakers
(`member_speakers`, deliberately not the PC/faculty roster) and external
`Speaker` rows, links the event to the PC workgroup for provenance, and sets
`published` only when the event has a real (non-TBD) date.

Rather than duplicate that logic in a fresh Event-create form, the direct
create **reuses** it: create an `EventProposal` and immediately `approve()` it
in the same request, then apply the publish/draft choice.

**Auto-approve is scoped to the action, not the person.** Approval happens
inline only in the new PC-admin view. There is no persisted "origin" flag and
nothing to track: a PC member using the normal `propose_event` form still lands
in the review queue exactly as today; only the PC-admin "+ New special event"
button mints immediately. This mirrors the existing Programs-tab "+ New event",
which already creates annual-program events with no review — the admin is the
authority surface; the queue exists for *other members'* proposals.

## Components

### View — `program_admin_special_event_new`

- Gated by `_is_pc_or_staff` (raise `Http404` otherwise), `@login_required`.
- Reuses `EventProposalForm` + `ProposalSpeakerFormSet`, with `event_type`
  **locked to `special_event`**: in the view, set
  `form.fields["event_type"].choices = [("special_event", "Special event")]`
  and `initial`. This both drives the template's type-adaptive display (only
  special-event fields show) and rejects any other `event_type` at validation.
- GET: render the form with `event_type=special_event`.
- POST: read the intended publish state from the submit button
  (`action=publish` vs `action=draft`). Set `form.require_complete = True`; if
  `form.is_valid()` and `speakers.is_valid()`, then inside
  `transaction.atomic()`:
  1. `proposal = _save_proposal_form(request, form, speakers, None, is_submit=True)`
     — sets `proposed_by = request.user`, status `PROPOSED`.
  2. `event = proposal.approve(request.user)` — mints + wires the event; the
     proposal row is now `APPROVED` (reviewer = proposer = the PC member).
  3. Apply the publish choice: if `action == "draft"`, force
     `event.published = False`; if `action == "publish"` and the event has a
     real date, ensure `event.published = True`. Save `published` if changed.
     (A TBD-date event cannot be published — it has only a placeholder date —
     so "publish" on a TBD event still yields a draft; the message says so.)
  - Atomicity guarantees we never leave a stray `PROPOSED` row in the queue if
    approval raises.
- On success: `messages.success(...)` (text reflects Published vs Draft) and
  redirect to `events:edit` for the minted event so the PC can finalize
  content. The draft message points them to the Proposals tab to publish when
  ready.

### View — `program_admin_special_event_publish`

- `@require_POST`, gated by `_is_pc_or_staff`.
- `get_object_or_404(Event, slug=…, event_type=Event.Type.SPECIAL_EVENT)` — the
  event_type filter keeps this control off annual-program events (whose
  visibility is Program-driven).
- Sets `event.published` from POST `action` (`publish` → True, `unpublish` →
  False); `save(update_fields=["published"])`. Guard: only publish if the event
  has a non-placeholder date (skip / message otherwise).
- Redirect back to the Proposals tab with a success message.

### URLs

Add to the events URLconf, PC-admin group:
- `admin-tools/programs/special-event/new/` → `program_admin_special_event_new`
- `admin-tools/programs/special-event/<slug>/publish/` →
  `program_admin_special_event_publish`

### Template — reuse `propose_event.html` via a `direct_create` flag

Pass `direct_create=True` in the context. Gate three things on it:

- **Header copy** — replace the "any member can propose … the PC reviews"
  framing with a short PC-admin line ("Create a special event. Save it as a
  draft, or publish it now.").
- **Form `action`** — point at `program_admin_special_event_new` instead of
  `propose_event`.
- **Buttons** — replace "Save for later" / "Submit for review" with two:
  **Save as draft** (`name="action" value="draft"`) and **Create & publish**
  (`name="action" value="publish"`).

Everything else — the type-adaptive fields and the toggle JS — is reused
unchanged. With `event_type` locked, the JS simply shows the special-event
field set.

### Proposals tab — button + Special-events management list

In `events/program_admin/proposals.html`:

- A `+ New special event` button in the tab header, linking to the create view.
- A new **Special events** section below the proposals: a table of
  `Event.objects.filter(event_type=SPECIAL_EVENT)` (newest first), each row
  showing the title, date, a **Draft / Live** badge (from `is_public_now`), an
  **Edit** link (`events:edit`), and an inline POST **Publish** / **Unpublish**
  button (to `program_admin_special_event_publish`). This gives special events a
  discoverable home and the publish-later control in one place.
- The view `program_admin_proposals` gains the special-events queryset in its
  context.

## Data model

No schema changes. The direct-created special event is a normal `Event`; its
`EventProposal` persists as an `APPROVED` audit record (proposer = reviewer =
the PC member). Draft vs live is the existing `Event.published` boolean.

## Edge cases

- **Incomplete form** → `require_complete=True` re-renders with errors; nothing
  is minted.
- **Save as draft with a real date** → event minted then forced
  `published=False`; hidden from the public, previewable by PC/staff.
- **Publish on a TBD-date event** → stays a draft (placeholder date); message
  explains it needs a date first.
- **Non-PC user** → `Http404` on every view (create, publish).
- **Non-special `event_type` POSTed** to create → rejected by the constrained
  choices.
- **Publish toggle aimed at a non-special event** → 404 via the `event_type`
  filter, so program events can't be toggled here.
- **Approval failure mid-request** → `transaction.atomic()` rolls back the
  proposal, so no stray queue item.
- **No notification storm** — proposal notifications fire from the review
  views, not from `approve()`/`_save_proposal_form`, so minting inline sends no
  "new proposal" notice to the PC.

## Testing (`events/test_program_admin.py`)

- PC member GETs the create page → 200, form present, type locked to special.
- POST `action=publish` with a complete dated payload → 302; an `Event` of type
  `special_event`, `published=True`, with a price tier and a first Session; the
  backing `EventProposal` is `APPROVED`.
- POST `action=draft` with the same payload → event minted `published=False`.
- POST `action=publish` with a TBD date → event minted `published=False`.
- Publish toggle: `program_admin_special_event_publish` with `action=publish`
  flips a draft special event to `published=True`; `action=unpublish` flips it
  back.
- Publish toggle refuses a non-special event (404).
- Non-PC user → 404 on create and publish views.
- POST attempting `event_type=seminar` on create → rejected (no seminar Event).
- The Proposals tab renders the Special events section with the Draft/Live
  badge.
