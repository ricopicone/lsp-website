# Turning registration approval on (and off) for a running seminar

Task #564. Design date 2026-08-12.

## The question

`Event.requires_faculty_approval` is a checkbox on the PC's event form. The
Program Committee chair wanted to turn it on for a seminar that already exists
and already has registered students, and nobody knew what that would do to
them.

## What it does today

The flag is read in exactly two places, both inside registration *creation* —
`registrations/views.py:74` (the normal form) and `:178` (the covered-by-tuition
one-click path). Nothing else in the codebase reads it.

So flipping it on an existing seminar is inert for everyone already registered.
An `AWAITING_PAYMENT` row stays payable through its Stripe button, a `PAID` row
stays paid, and only registrations created *after* the flip land in
`PENDING_APPROVAL`. There is no migration, no backfill, and no data risk.

That grandfathering is the right behaviour and this design keeps it. Pushing
existing `AWAITING_PAYMENT` rows back into the queue would take a place away
from someone who was told they had it, and would need their open Checkout
sessions expired to be safe (the #561 hazard). Rejected.

What the grandfathering is *not*, today, is stated anywhere. It is an emergent
property of where the flag happens to be read — the same shape of accident as
the dead `Program.public_program_year_q()` in #532 — so this design pins it with
a test and says it out loud in the help text.

## Four gaps, and what closes them

### 1. Turning it back off strands the queue

Off is not the inverse of on. Pending rows stay `PENDING_APPROVAL` until a human
decides each one, and `send_registration_reminders` keeps nudging the faculty
every three days about a queue the event no longer has a reason to hold. There
is no bulk approve anywhere, so a popular seminar means clicking through them
one at a time to undo a decision that was one checkbox to make.

New `registrations/services.py::release_pending_approvals(event, by)`, beside
`comp_registration` (the existing home for a shared side-effect chain). It walks
the event's pending rows, calls `reg.approve(by)`, and notifies each member
through the same chain `approve_registration` uses — `registration_approved`
when a fee is still due, `registration_confirmed` when the row is $0 or
tuition-covered. It returns the rows it released, so the caller's message is
built from what actually changed rather than a stale in-memory copy (#485,
#561). It is idempotent by construction: `approve()` returns False on a row that
is no longer pending, so a second pass sends nothing.

Both edit views call it when the flag went True→False. **The before-value is
snapshotted before the form is bound**, because `ModelForm` validation mutates
the instance in place — reading it afterwards compares the new value against
itself, which is precisely what made `changed_reviewable_fields()` silently
wrong in #532. `event_edit` already snapshots its reviewable fields this way at
`events/views.py:381`; this joins that snapshot.

**The Django admin deliberately does not fire it.** Same rule as #485's staff
paths: the admin is the raw escape hatch, and a `post_save` signal on `Event`
would let any script that touches an event mail members. Staff who want the
queue cleared use the form or the registrar console.

### 2. Faculty cannot reach the switch

`requires_faculty_approval` is on `ProgramEventForm` (the PC's form) and in the
Django admin. It is not on the faculty-facing `EventEditForm`, so the person
actually running the seminar has to ask the PC to change how their own
registrations work.

It joins `EventEditForm.Meta.fields` with a checkbox on `event_edit.html`. Two
traps:

- **It stays out of `REVIEWABLE_FIELDS`.** Review protects content the PC
  approved; who may enrol is not that, and there is no prior value for the PC to
  have approved. So it applies immediately through the existing non-reviewable
  path, in both the straight-through save and the dialog's decision POST.
- **`event_edit_confirm.html` re-posts every field as a hidden `<textarea>`**,
  which silently eats a checkbox. It joins the `record_video` / `tuition_covers`
  exception there, following the precedent set in #504 and #532. Without this,
  the toggle would be dropped on exactly the events that route through change
  review.

The gate is `can_edit_event`, so a reading group's conveners get the switch too
— they hold ORGANIZER rather than FACULTY (#495), and `can_edit_event` already
knows it.

### 3. The approval notice misses conveners

`approve_registration` and `decline_registration` are gated on `can_edit_event`,
so a convener **can already approve** — they are simply never told there is
anything to approve. `registration_pending` notifies `Event.faculty_members()`,
which filters `role=FACULTY` (`events/models.py:669`), and a reading group's
conveners hold ORGANIZER. On a convener-led offering the bell reaches nobody and
the email falls back to `SUPPORT_EMAIL`, the Web Coordinator's address — the
school's own inbox standing in for the person who should have been asked.

New `events/permissions.py::offering_leads(event)`: the event's faculty, plus
the serving lead-role members of the offering's own workgroup for the types
where leadership means running the offering (`LEAD_LED_EVENT_TYPES`, already
defined there for `_leads_offering`). Deduped, order preserved.
`registration_pending` and `send_registration_pending_notice`'s recipient list
adopt it, as does the approval-reminder digest.

`Event.faculty_members()` is **not** changed. It answers "who teaches this",
which is a different question — it drives bylines, the roster, and the PC form's
initial selection, and widening it would put conveners on surfaces that mean
instructor.

### 4. The bell drops faculty on the wrong page

`payments/notifications.py:194` hardcodes `events:detail?view=faculty`, but
`event_detail` redirects the annual-program types to their Workspace
(`events/views.py:272`) and the query string does not survive the redirect. So
the bell lands on the Overview tab, with no approve buttons anywhere on it. The
*email* is already correct — it uses `_faculty_tools_url`, which resolves to
`?tab=roster` for an offering.

The bell adopts `_faculty_tools_url` too. Both callers live in `payments` and
`notifications` already calls into `emails`, so this is a rename to
`faculty_tools_url` and one import, not new plumbing.

`Notification.url` is stored on the row, so a link fix normally needs a data
migration to repair rows already sent. Not here: no event has ever carried the
flag, so no such notification exists. **Verify that on prod before deploying**
rather than assuming it.

## Disclosure

Nothing tells a member that registration is reviewed. `requires_faculty_approval`
appears in no member-facing template — the event page and register form look
identical either way, and the member finds out on the confirmation page, after
committing. Mid-run that is worse: two people register a day apart and get
materially different outcomes with nothing on the page to explain it.

One line, rendered only when the flag is on, in three places: the event page
beside the Register CTA (`_event_summary.html:232`), the register form, and the
covered-by-tuition confirm page — which is a single click straight to a pending
row and so needs it most.

> Registration for this seminar is reviewed by the faculty before it's confirmed.

Wording follows the house rule for member-facing copy: say what happens, not
why, and commas rather than em dashes.

On both edit forms the help text states the whole rule in both directions, since
that is the question that started the task: new registrations need approval,
anyone already registered keeps their place, and unticking it approves everyone
still waiting. The model field's `help_text` currently reads "future
proposal-flow option… all existing seminars are off", which is stale on both
counts and gets rewritten. That is the only migration.

## Testing

- Grandfathering: flipping the flag on an event with `AWAITING_PAYMENT` and
  `PAID` registrations leaves every one of them untouched, and the next
  registration is `PENDING_APPROVAL`.
- Release: unticking approves every pending row, routes $0 to `PAID` and a fee
  to `AWAITING_PAYMENT`, notifies each member once, and is a no-op on a second
  save. Ticking it on does *not* release anything.
- The Django admin path does not release.
- `EventEditForm` carries the field, and the value survives the change-review
  dialog's re-post.
- `offering_leads` includes a reading group's ORGANIZER conveners and the
  seminar's FACULTY, and `faculty_members()` is unchanged.
- The disclosure renders on all three surfaces only when the flag is on.

## Not doing

- **Retroactive review of existing registrants** (above).
- **A bulk "approve all" button** for the ordinary case. Releasing the queue is
  the answer to the specific question "I turned this off"; a general bulk
  approve is a different feature, and approving people one at a time is the
  point of an approval queue.
- **A confirmation interstitial before releasing.** The release only ever grants
  what the member asked for, and the checkbox's help text says what unticking
  does before it is unticked. Compare #485, which does interpose one, because
  there the member's fee changed.
