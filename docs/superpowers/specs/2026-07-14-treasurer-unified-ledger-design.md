# Treasurer unified member ledger—design (task #439)

**Date:** 2026-07-14
**Status:** Approved by Rico (brainstorming session)
**Supersedes:** the per-category "ledger" organization of the treasurer admin (separate Dues/Tuition tabs, per-period dues binding, category-specific record buttons). Builds directly on the task #437 cumulative tuition-coverage model—generalizing it to all money.

## Problem

The treasurer admin treats dues, tuition, registrations, and donations as separate ledgers with different mechanics:

- **Dues** is a per-period binary: "paid" means a SUCCEEDED `Payment` FK-bound to that exact `DuesPeriod` (`payments/dues.py:user_paid_for_period`). No partial, no cumulative, no per-member override.
- **Tuition** (since #437) is cumulative: one pot of tuition money swept oldest-first across obligated years.
- **Registrations/donations** float alongside.

Historical data is too weak to keep the categories' books separate—money orphans, phantom credits hide real shortfalls, and the treasurer has to learn a different mental model per tab. The school's actual need is one account per member where all charges go, categorized and filterable, with derived sums (e.g. total tuition paid).

## Decisions (settled with Rico, 2026-07-14)

1. **Fungibility: one net balance.** All charges and payments roll into one running balance per member; coverage sweeps oldest-charge-first regardless of category. A dues overpayment can cover tuition. Category tags stay on every line for filtering and sums.
2. **Charge scope: dues + tuition + individual event registrations** (when not covered by tuition). Donations never mint charges.
3. **Dues history: backfill to the first full AY with decent records** (20–21 or 21–22—pick by inspecting the imported payment data during implementation). Backfilled charges carry `assumed` provenance and are waivable/adjustable.
4. **Tabs: collapse Dues/Tuition into Accounts.** Linkable filtered views replace the per-category rosters.
5. **Implementation shape: materialized charges** (new model), not a derived/virtual ledger and not double-entry allocation (per-payment allocation was already proven untenable in #437).

## 1. Data model

### New model: `payments.Charge`

A debit row in a member's account.

| Field | Notes |
|---|---|
| `user` | FK to `accounts.User`, indexed |
| `category` | `dues` / `tuition` / `registration` (same vocabulary as `Payment.Type` minus `donation`) |
| `amount`, `currency` | Decimal USD, mirrors `Payment` |
| `effective_date` | Orders the oldest-first sweep. AY start date for dues/tuition; settle date for registrations |
| `status` | `OPEN` (counts toward obligation) / `WAIVED` (treasurer forgave—excluded from obligation, kept for audit) / `VOID` (cancelled registration, enrollment flipped to skipping) |
| `dues_period` / `tuition_period` / `registration` | Optional FKs for labeling and mint idempotency |
| `source` | Provenance, same vocabulary as `Payment.Source` (imported / assumed / verified / staff-entered) |
| `staff_adjusted` | Boolean; set whenever a treasurer edits amount/status. Sync functions never touch rows where this is true |
| `notes` | Append-only audit trail, same convention as `Payment.notes` |
| `created_at` | |

Uniqueness: at most one non-VOID charge per `(user, category, dues_period)` and `(user, category, tuition_period)`; registration charges unique per `registration`.

### Ledger math (read-time, no allocation rows)

- **Obligation** = sum of OPEN charges.
- **Paid** = sum of SUCCEEDED payments of type dues/tuition/registration. Donations are listed in the statement but never offset obligations. Refunded payments don't count.
- **Balance** = obligation − paid (positive = owes, negative = paid-ahead credit).
- **Per-charge coverage** = sweep the one pot across OPEN charges ordered by `effective_date` oldest-first → Paid / Partial / Unpaid per charge. Derived at read time; never stored.
- **Total tuition paid** = sum of tuition-categorized succeeded payments (a reporting sum, not a settlement mechanism).
- **Tuition requirement progress** = count of tuition charges the sweep has fully covered, out of `TUITION_YEARS_REQUIRED` (4).

### What existing models keep doing

- `TuitionEnrollment` remains the authoritative per-year decision record. `Profile.is_tuition_current()`, `covers_seminars`, and both registration gates are untouched.
- `TuitionInstallment` remains payment-plan scaffolding (not balance-driving—already true since #437).
- `Payment.dues_period` / `tuition_period` / `tuition_installment` stay as informational provenance but stop driving any status. `payments/dues.py:user_paid_for_period` is retired; "dues current" = the member's current-AY dues charge is fully covered by the sweep.
- Columns are not dropped in this task.

## 2. Charge minting

Every automated path keeps a manual override (do-not-over-automate).

- **Dues**: idempotent `sync_dues_charges(period)` mints one OPEN charge per obligated member (`is_dues_obligated`) at their role tier. Runs at AY rollover (existing dues cron) and from a treasurer button. The amount is fixed at mint time; role changes are treasurer adjustments, not auto-edits.
- **Tuition**: idempotent `sync_tuition_charges(user)` recomputes from enrollment decisions—each non-skipping enrolled year mints a charge at that year's rate, capped at the first 4 non-skipping years oldest-first; a 5th enrolled year mints nothing ("requirement met"). Fires on `TuitionEnrollment` save. A year flipped to skipping VOIDs its charge (which may pull the next year into the cap).
- **Sync safety rule**: sync functions only manage rows they minted and never touch `staff_adjusted` rows. When sync disagrees with a staff-adjusted row, it records a conflict surfaced on the Reconcile tab instead of clobbering.
- **Registration**: minted at settle time so abandoned checkouts never create debt. PAID mints an OPEN charge alongside its payment (amount = the payment amount); COMPED mints a pre-WAIVED charge so the comp shows in the statement; cancel/refund VOIDs the charge. Tuition-covered and $0 registrations mint nothing.
- **Manual**: Add charge / Adjust amount / Waive / Void actions on the member account page, each logging actor + date to `notes` and setting `staff_adjusted`.

## 3. Treasurer UI—9 tabs become 7

**Overview · Accounts · Payments · Reconcile · Settings · Exports · Help.** The Dues and Tuition tabs are removed; the Members tab is replaced by Accounts.

- **Overview**: current-AY tiles computed from the ledger (collected by category, total outstanding, members owing) plus one consolidated **Needs-attention queue**: undecided students, committed-without-payment, charge conflicts, provisional and no-payer reconcile counts. Each item links to the right filtered view.
- **Accounts** (the centerpiece): roster of members with ledger activity—name, role, balance (owed / credit / square), tuition progress (n of 4), current-AY dues state, last payment date. Sortable and filterable (owing/credit/square, category, role); filter+sort state lives in the querystring so views are **linkable**—the linkable filtered views are the replacement for the old Dues/Tuition rosters.
- **Member account page** (replaces `member_detail`): a statement—chronological charges + payments with running balance, header tiles (balance, total tuition paid, tuition years n/4, current-AY dues state). All per-member actions in one place: add/adjust/waive/void charge; one generic **Record offline payment** (category + amount, defaulting from the uncovered charge) replacing the separate dues/tuition record buttons; refund / mark-paid / resend receipt on payment rows; the tuition decision setter (committed/skipping). Event registrations section stays.
- **Payments**: as today (already unified); keeps type/status filters and row actions.
- **Reconcile**: keeps the provisional-payment and no-payer queues; gains the **charge-conflict queue** (sync vs staff-adjusted disagreements; also the "paid past obligation while a year is Skipping" flag from #437).
- **Settings**: unchanged—per-AY dues tiers and tuition amounts still drive minting.
- **Exports**: existing transactions CSV plus a new **balances CSV** (member, role, obligation, paid, balance, tuition progress).
- **Help**: `core/docs/treasurer-guide.md` rewritten for the unified model.

## 4. Migration and backfill

One data migration mints history, then a parity check gates the UI cutover:

1. **Dues charges** back to the chosen start AY. Create any missing `DuesPeriod` rows for those years (tier amounts per historical knowledge, treasurer-adjustable). Tier chosen from the member's current role, `source=assumed`. Expect this to surface real "owed" balances—the Accounts view filtered to owing + assumed provenance is the treasurer's cleanup worklist, with per-row waive/adjust.
2. **Tuition charges** from existing `TuitionEnrollment` rows (non-skipping, 4-year cap oldest-first), amount from each year's `TuitionPeriod` rate, provenance mirroring the enrollment's confidence.
3. **Registration charges** from existing PAID/COMPED registrations (PAID → OPEN with the payment amount; COMPED → WAIVED), `effective_date` = settle date.
4. **Parity report**: a management command (`audit_ledger`) compares old-model numbers (dues paid-flags per period, per-member tuition summaries) against the new sweep for every member and prints diffs. Run on a prod snapshot and review before deploying the UI cutover. Known-acceptable diffs: members square under fungibility who were split credit/debt under per-category books.

**Launch dependency**: because the sweep is oldest-first, un-reconciled `assumed` backfilled dues debt would make the landing banner (and, once re-enabled, dues reminders) fire even for members who paid the current year. The treasurer's waive-or-verify pass over assumed charges must happen before the member-facing timers are re-enabled at launch—add it to the launch checklist.

## 5. Code consolidation and blast radius

- New **`payments/ledger.py`** replaces the four context builders (`_treasurer_dues_context`, `_treasurer_tuition_context`, `_tuition_coverage`, `_member_tuition_summary`): `member_account(user)` (statement, balance, category sums, tuition progress) and `accounts_overview()` (batched roster, no N+1). Minting syncs live in `payments/charges.py`. Ledger math moves out of the 1820-line `views.py`.
- **Landing banner** (`core/views.py`): becomes "outstanding balance of $X" from the unified balance instead of dues-only.
- **Dues reminders** (`send_dues_reminders`): key off "current-AY dues charge not fully covered" instead of `user_paid_for_period`. Tuition reminders (decision-based) unchanged.
- **Member-facing Money tab** (`formation/views.py`): keeps its current UI, repointed at the new helpers so numbers agree. A full member-facing statement is a follow-up task, not this one.
- **Untouched**: registration gates and pricing (`events/pricing.py`, `registrations/views.py`), survey payment creation, receipts/emails, Stripe checkout/webhook, `complete_payment` tuition side-effects, transactions CSV, Django admin.

## 6. Testing

- Unit tests on `ledger.py`: fungibility across categories, oldest-first sweep with partial coverage, 4-year cap and "met" state, WAIVED/VOID exclusion, donations excluded, refunds excluded, credit balances.
- Minting: idempotent re-runs (rollover twice, enrollment resave), enrollment flips (skipping ↔ committed, cap re-pull), staff-adjusted rows never clobbered, conflict recording, registration settle/comp/refund lifecycle.
- Migration test on a fixture ledger covering each backfill class.
- View tests for Accounts (filters, sorting, linkability), member account actions, Overview queue, Reconcile conflict queue.
- Adapt (don't delete) the existing tuition-coverage tests; `audit_ledger` doubles as the prod verification step.

## Out of scope

- Dropping the retired `Payment` FK columns.
- Member-facing statement UI redesign.
- Double-entry allocation of payments to charges (explicitly rejected).
- Bulk waive tooling (per-row actions only; bulk cleanup goes through the Web Coordinator if needed).
