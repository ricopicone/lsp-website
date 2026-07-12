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

## Goal

Give the PC a one-step "+ New special event" create action in the PC admin
that mints a fully wired, published (when dated) special event.

### Non-goals

- Other standalone types (Day of Assembly, Working Day, Scholarly Seminar)
  stay in Django admin — rare and institutional.
- Full in-app *editing* of a special event after creation (access_info,
  pricing tiers) is unchanged: `events:edit` (limited content fields) or Django
  admin. A separate follow-up if wanted.
- The member-facing propose flow is untouched.

## Approach — reuse the proposal → approve pipeline

`EventProposal.approve()` already encapsulates the non-trivial minting of a
special event: builds the **price tier** from the proposed fee, turns the
date/time into the event's first **Session**, wires internal speakers
(`member_speakers`, deliberately not the PC/faculty roster) and external
`Speaker` rows, links the event to the PC workgroup for provenance, and sets
`published` only when the event has a real (non-TBD) date.

Rather than duplicate that logic in a fresh Event-create form, the direct
create **reuses** it: create an `EventProposal` and immediately `approve()` it
in the same request.

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
- POST: set `form.require_complete = True`; if `form.is_valid()` and
  `speakers.is_valid()`, then inside `transaction.atomic()`:
  1. `proposal = _save_proposal_form(request, form, speakers, None, is_submit=True)`
     — sets `proposed_by = request.user`, status `PROPOSED`.
  2. `event = proposal.approve(request.user)` — mints + wires the event; the
     proposal row is now `APPROVED` (reviewer = proposer = the PC member).
  - Atomicity guarantees we never leave a stray `PROPOSED` row in the queue if
    approval raises.
- On success: `messages.success(...)` and redirect to
  `events:edit` for the minted event so the PC can finalize content. A TBD-date
  event mints unpublished (per `approve()`); the message notes that.

### URL

Add `program_admin_special_event_new` to the events URLconf, in the PC-admin
group (e.g. `admin-tools/programs/special-event/new/`).

### Template — reuse `propose_event.html` via a `direct_create` flag

Pass `direct_create=True` in the context. Gate three things on it:

- **Header copy** — replace the "any member can propose … the PC reviews"
  framing with a short PC-admin line ("Create a special event. It's published
  immediately once it has a date.").
- **Form `action`** — point at `program_admin_special_event_new` instead of
  `propose_event`.
- **Buttons** — replace "Save for later" / "Submit for review" with a single
  **Create event** button (`name="action" value="submit"`).

Everything else — the type-adaptive fields and the toggle JS — is reused
unchanged. With `event_type` locked, the JS simply shows the special-event
field set.

### Entry point — Proposals tab button

Add a `+ New special event` button to the header of
`events/program_admin/proposals.html`, linking to the new view. The Proposals
tab is where special-event proposals are already reviewed, so all special-event
activity stays in one place.

## Data model

No schema changes. The direct-created special event is a normal `Event`; its
`EventProposal` persists as an `APPROVED` audit record (proposer = reviewer =
the PC member).

## Edge cases

- **Incomplete form** → `require_complete=True` re-renders with errors; nothing
  is minted.
- **Non-PC user** → `Http404` on GET and POST.
- **Non-special `event_type` POSTed** → rejected by the constrained choices.
- **TBD date** → event mints unpublished (existing `approve()` behavior); the
  success message says so.
- **Approval failure mid-request** → `transaction.atomic()` rolls back the
  proposal, so no stray queue item.
- **No notification storm** — proposal notifications fire from the review
  views, not from `approve()`/`_save_proposal_form`, so minting inline sends no
  "new proposal" notice to the PC.

## Testing (`events/test_program_admin.py`)

- PC member GETs the create page → 200, form present, type locked to special.
- PC member POSTs a complete special-event payload → 302; an `Event` of type
  `special_event`, `published=True` (dated), with a price tier and a first
  Session exists; the backing `EventProposal` is `APPROVED`.
- POST with a TBD date → event minted `published=False`.
- Non-PC user GET/POST → 404.
- POST attempting `event_type=seminar` → rejected (no seminar Event created).
