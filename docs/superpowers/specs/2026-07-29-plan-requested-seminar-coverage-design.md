# A requested payment plan covers seminars

**Task:** #484 — "Requesting a payment plan should give provisional access to
seminars, just as tuition-paying commitment does. We have been holding them
waiting for board approval, but that's going to take too long. Stop blocking just
like committing to paying unblocks."
**Date:** 2026-07-29

## Problem

Applying for a payment plan is a request to the Board, not a self-serve status
(task #450 phase B): the member's `TuitionEnrollment` records
`PLAN_REQUESTED` and a PENDING `TuitionPlanApplication` carries their reasons.
`PAYMENT_PLAN` is reached only once the Board approves.

The Board's turnaround is the problem. Registration for the fall is open now, and
a member waiting on that decision is treated as not paying tuition in the
meantime.

The hold is narrower than "blocked", and worth stating exactly, because it
changes what has to be fixed:

- `PLAN_REQUESTED` **already clears** the broad no-decision gate. The row exists,
  so `registrations.views._tuition_block_reason` lets them register
  (`registrations/test_event_ay_gate.py::test_plan_requested_not_blocked_but_not_covered`).
- What it does not do is grant coverage. `TuitionEnrollment.covers_seminars`
  lists COMMITTED / PAYMENT_PLAN / PAID_IN_FULL only, so
  `Profile.is_tuition_current()` is False, no `covered_by_tuition` tier resolves,
  and **the member is quoted the full seminar fee** until the Board acts.
- The charge side already disagrees with that reading.
  `payments.charges._owed_periods` exempts only SKIPPING, so a plan request
  already mints its tuition charge. The school already treats the money as owed
  while withholding what paying it buys.

A second, separate hold sits on top for special events. `_tuition_block_reason`'s
narrow gate blocks a COMMITTED member from an event in
`TUITION_BLOCKING_EVENT_TYPES` (only `special_event`) when a covered tier would
otherwise apply, on the grounds that they would be claiming coverage they have
not paid for. Coverage is per event, not global: it exists only if the event
carries a `PriceTier` with `covered_by_tuition=True` matching their role or
`all`, so an event offering no coverage is unaffected either way. Where coverage
does exist, the gate blocks registration outright rather than falling back to the
regular fee.

## Decision

**Coverage follows any non-skipping decision on file.** `PLAN_REQUESTED` joins
`covers_seminars`. A pending plan request buys the same thing a commitment buys.

**The narrow special-event gate is removed entirely.** Rico's call (2026-07-29):
put the two states in parity *and* waive the fee for both on a tuition-eligible
special event, on the assumption tuition will be paid. This widens policy for
COMMITTED members beyond the task's headline and removes the only place in the
codebase where "committed but no money yet" had teeth. That is intended.

`TUITION_BLOCKING_EVENT_TYPES` is deleted rather than emptied. A frozenset with
nothing in it, or a settings flag, is a config point nobody reads and two paths
to test; reversing this policy is a revert, as with #483.

**The broad gate stays.** A member with no enrollment row for the event's period
is still blocked from registering for anything. Some decision must be on file;
a plan request is one, and always was.

**Nothing unwinds on decline.** Declining still deletes the `PLAN_REQUESTED` row,
dropping the member to no-decision where the broad gate applies again. A seminar
they already registered for at $0 stands, and staff settle it by hand
(do-not-over-automate). The decline notification says so.

## Design

### `payments/models.py` — `TuitionEnrollment.covers_seminars`

Add `PLAN_REQUESTED` to the returned set. Rewrite the docstring: coverage follows
any non-skipping decision, including a plan request awaiting the Board's
decision, because the year's tuition charge is already minted either way. Only
SKIPPING declines to cover, and pays the regular per-event fee.

This property is the single source. `Profile.is_tuition_current()` reads it, and
both consumers (`events.pricing.resolve_price`'s covered short-circuit and
`registrations.views._find_covered_tier`) read that. No other call site changes.

### `registrations/views.py` — `_tuition_block_reason`

Delete `TUITION_BLOCKING_EVENT_TYPES` and the second `if` that uses it. The
function keeps its `owes_tuition` / `tuition_decision_exempt` / `period_for_event`
preamble and the no-row branch, and returns None otherwise. Rewrite the docstring
from a two-layer policy to one gate, and record that a tuition-eligible special
event is now covered for any non-skipping decision.

`registrations/templates/registrations/blocked_tuition.html` still serves the
remaining gate. Unchanged.

### `payments/ledger.py` — the Decision column

`member_account` builds the per-year tuition rows and reads a fully covered year
as "Paid" for COMMITTED and PAYMENT_PLAN (`payments/ledger.py:199`). Add
`PLAN_REQUESTED`, so a year that is
actually covered stops showing a stale "Payment plan requested" on the treasurer's
tuition table. Cosmetic, and in the same conceptual spot as the change above.

### Copy

Member-facing strings use commas, not em dashes (the 2026-07-06 convention).

`formation/templates/formation/_tab_account.html` — the pending-application note
("Your payment plan application is with the Board.") gains a sentence: in the
meantime tuition covers seminar fees, just as it does for anyone paying tuition
this year. Both the current-period and upcoming-period blocks carry this note;
both get the sentence. This is the whole disclosure that coverage is already
live.

`payments/templates/payments/tuition_plan_queue.html` — the Board's queue intro
gains a sentence: a pending request already carries seminar coverage, so
approving sets the installment schedule rather than unlocking registration.
Without it the Board reads its own queue as the thing holding members up.

`payments/notifications.py` — `notify_plan_application_decided`'s decline branch
gains a line: if they registered for anything with tuition coverage while the
application was pending, the school will be in touch about settling it. The
approve branch is unchanged.

## Tests

Each starts as a failing test.

- `registrations/test_event_ay_gate.py` — rewrite
  `test_plan_requested_not_blocked_but_not_covered`: `PLAN_REQUESTED` now
  resolves a covered tier and still is not blocked. The name inverts to
  something like `test_plan_requested_is_covered`.
- `registrations/test_views.py` —
  `test_special_event_blocks_committed_student_when_event_is_tuition_covered`
  flips to allows-and-covers (the registration is created at $0). Add the
  `PLAN_REQUESTED` twin on the same fixture.
- `accounts` / `payments` — `Profile.is_tuition_current()` is True for a
  current-period `PLAN_REQUESTED` row.
- `formation/test_account_tab.py` — the pending-application note mentions
  coverage.

Must stay green untouched, as the boundary of the change:

- a member with no enrollment row is blocked from every event type;
- SKIPPING pays the regular fee and is not blocked;
- COMMITTED on a special event with no covered tier for their role pays the
  regular fee;
- `tuition_decision_exempt` short-circuits the gate.

## Out of scope

- **The ledger.** No migration, no backfill, no data change. A plan request
  already mints its tuition charge, so obligations and balances cannot move.
- Board review itself, `TuitionPlanApplication`, and the approve →
  `PAYMENT_PLAN` → choose 2 or 9 installments flow.
- `send_balance_reminders`, which still skips `PLAN_REQUESTED` while the Board
  holds the application.
- The pay-in-full button, offered only for COMMITTED with no installments. A
  member with a pending request who wants to pay outright still goes through
  the treasurer.
- No feature flag and no `FormationSettings` field.
- The pre-existing wart that a blocked member got a 403 rather than a fallback
  to the regular fee. Deleting the gate makes it moot here; it is not
  reintroduced elsewhere.

## Accepted risk

A member requests a plan, registers for a covered seminar at $0, and the Board
declines. They keep the covered registration with no tuition decision on file,
and the broad gate then asks them for a new decision before they register for
anything else. That is the cost of provisional access, taken deliberately: the
decline notification surfaces it and staff settle by hand.
