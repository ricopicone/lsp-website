# Fall 2026 tuition & registration launch — design (task #450)

Decisions approved by Rico 2026-07-22. Pricing tiers and the Oct 31 decision
date are already applied; this spec covers the remaining four phases.

## Context

Fall registration opens with the 2026-27 program. Today the tuition gate and
covered-by-tuition pricing key on the TuitionPeriod containing **today**, so
July/August registrants are judged against AY 2025-26. The payment-plan
decision is currently self-serve. Tuition has a decision deadline but no
payment-due concept. Nothing links outstanding balances to seminar-group
access.

Dates set by the school: **decision due Oct 31, 2026; tuition and dues due
Nov 30, 2026.**

## A. Event-AY-aware gate and coverage (pre-opening blocker)

The gate and coverage resolve the tuition period from the **event**, not from
today.

- New helper `payments.ledger.period_for_event(event)`: the TuitionPeriod
  containing `event.start_date` (annual-program types); falls back to
  `TuitionPeriod.current()` when the event has no dates or is not
  program-owned (special events, Days of Assembly).
- `registrations.views._tuition_block_reason(user, event)` uses that period:
  an in-training member registering in July for a 2026-27 seminar must have a
  **2026-27** decision on file (any decision, Skipping included).
- `_find_covered_tier` and `Profile.is_tuition_current` gain a period
  argument; coverage requires a covers-seminars enrollment **for the event's
  period** (a 25-26-paid member is not covered for a 26-27 seminar without a
  26-27 decision).
- Member Account tab: the decision panel offers the upcoming period as soon
  as its TuitionPeriod exists (currently it only surfaces the period
  containing today). Both the current and next period render, each with its
  own decision state.

## B. Payment plan becomes a Board application

The "payment plan" decision option is replaced by **Apply to the Board for a
payment plan**.

- New `TuitionEnrollment.Status.PLAN_REQUESTED` (`covers_seminars=False`).
  Choosing the option requires a reasons textarea and writes the enrollment
  row (so the single source of truth for the gate stays TuitionEnrollment) —
  a pending application **counts as a decision** (unlocks general
  registration) but does **not** confer coverage.
- New model `payments.TuitionPlanApplication`: user, tuition_period, reasons,
  status (PENDING / APPROVED / DECLINED), decided_by, decided_at, note. One
  open application per user+period.
- Review surface: a queue visible to **Board members** (Board committee
  roster), notification on submit; approve flips the enrollment to
  PAYMENT_PLAN (covers seminars), decline reverts the enrollment to
  no-decision and notifies the member to choose pay-in-full or skip.
  Approve/decline both leave an audit trail (application row + notification).
- Update the Tuition Assistance document (documents app, inline-HTML body) to
  describe the Board application and the Oct 31 / Nov 30 dates.

## C. Payment-due dates

- `TuitionPeriod.payment_due_date` (new nullable DateField) — set 2026-11-30
  for AY 2026-27. `DuesPeriod.due_date` for 2026-27 → 2026-11-30 (data edit,
  field exists).
- `send_tuition_reminders` keys its unpaid-committed nagging off
  `payment_due_date` (decision nags stay keyed to `decision_due_date`).

## D. Outstanding-balance runway and manual access cutoff

Simplified to one predicate: **outstanding ledger balance past due**.

- Reminder ladder: after Nov 30, a weekly balance reminder (member's total
  outstanding balance across dues/tuition/registration, from the unified
  ledger) with a link to the Account tab. Reuses the ThrottledSender pattern
  and the period's reminder interval.
- Treasurer visibility: Accounts → Owing already lists balances; add
  "past due, reminded N times, last reminded" columns so the treasurer can
  see who is approaching a cutoff.
- Suspension is **manual** (do-not-over-automate): a per-member, audited
  treasurer action ("suspend seminar-group access until balance cleared")
  that excludes the member from registration-derived seminar Workgroup
  rosters; reversible, visible on the member account page. No automatic
  cutoff ships.

## Sequencing

1. **A + C** — required before opening fall registration.
2. **B** + Tuition Assistance doc — before decision season ramps (well ahead
   of Oct 31).
3. **D** — after launch, in place before Nov 30.

## Open points

- Exact placement of the Board review queue (Board workspace tab vs. an
  /admin-tools/ page gated to Board membership).
- Whether declined applicants get a grace window before the gate re-blocks
  registration.
