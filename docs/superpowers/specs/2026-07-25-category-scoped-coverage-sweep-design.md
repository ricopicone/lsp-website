# Category-scoped coverage—design (task #473)

**Date:** 2026-07-25
**Status:** Approved by Rico
**Amends:** decision 1 ("Fungibility: one net balance") of
`2026-07-14-treasurer-unified-ledger-design.md`.

**The single account ledger is the ground truth and stays fully intact.**
One obligation, one paid total, one net balance, one running statement,
across every category — exactly as #439 specified. Nothing in this change
moves a balance.

What changes is the **meta accounting**: the per-category readings taken off
that ledger (per-charge coverage, the tuition year table, `tuition_years_covered`,
dues state). Those are category questions and are now answered from that
category's charges and payments alone. **No fungibility in the meta
accounting** — not even for a surplus.

## Problem

Rico's account showed three tuition years fully paid **plus "$1,870.00 /
$2,000.00" on a fourth**, against $6,000 of tuition payments on the ledger —
coverage claiming $1,870 more tuition than had ever been paid as tuition.

`payments/ledger.py:_charge_states` swept one pot of *all* non-donation
payments across *all* OPEN charges oldest-first, category ignored. On that
account the pot was $7,970 — $6,000 tuition, $400 dues, $1,570 registration —
and tuition years sort oldest, so the dues and registration money was
retro-credited to a 2023 tuition year. The $1,870 is exactly the non-tuition
money ($1,970) minus the one dues charge that sorted ahead of the last tuition
year ($100).

The mirror image was equally wrong: four registration fees paid in full on the
day (two from that week) read as **unpaid**, their money having been absorbed
by older tuition charges.

Two things made this more than cosmetic:

- **`tuition_years_covered` gates promotion.** It feeds
  `ledger.tuition_clearance()`, the "Requirement met" badge on My LSP →
  Account, `tuition_decision_exempt()`, the treasurer Accounts column and the
  balances CSV. Registration-fee money could advance a member's tuition-year
  count.
- **The same function contradicted itself.** `member_account()` reported
  `total_tuition_paid = $6,000` and `tuition_overpaid = $0` (both correctly
  tuition-scoped) next to a year table built from the category-blind sweep.

The net balance was right throughout ($2,000 owed = the one genuinely unpaid
tuition year). Only the attribution was wrong.

## Decision

### 1. Coverage is strictly within a category

`_charge_states(open_charges, paid_by_category)` covers each category's OPEN
charges oldest-first from that category's counting payments. There is no
second pass and no spillover. Money left over in a category settles nothing
elsewhere — it is still on the ledger and still in the balance, as credit.

An intermediate design (category-scoped *then* spill the surplus) was built and
rejected: spillover is fungibility, and it reintroduced exactly the confusion
the change exists to remove — a registration overpayment could still advance a
tuition year.

Consequences, stated deliberately:

- A dues overpayment does **not** cover tuition. It is dues credit.
- A payment in a category the member has no charges in covers nothing.
- A miscategorized payment now *shows up* as an unpaid charge in the category
  that's short. **That is the point** — the fix is to re-categorize the
  payment (treasurer and member both have that action), not to let the wrong
  bucket quietly read as paid.
- `send_dues_reminders` keys off `dues_state`, so a member whose dues charge
  was being silently covered by tuition money is now correctly reminded.

### 2. Dues gets the bucket treatment tuition already had

Dues is tracked cumulatively, as its own bucket with its own balance:

| Key | Meaning |
|---|---|
| `dues_obligation` | Sum of OPEN dues charges |
| `total_dues_paid` | Sum of counting dues payments |
| `dues_balance` | `dues_obligation − total_dues_paid` |
| `dues_owed` / `dues_credit` | The positive/negative halves |
| `dues_rows` | Per-year rows (period, amount, covered, state), newest first |

`accounts_overview()` carries `dues_obligation` / `dues_balance` /
`dues_owed` / `dues_credit` per row. The existing current-AY `dues_state`
badge is unchanged and stays.

## Implementation

- `payments/ledger.py`
  - `_paid_by_category(payments)` — counting payments summed by `Payment.Type`
    (same vocabulary as `Charge.Category`, minus donation).
  - `_charge_states(open_charges, paid_by_category)` — takes the per-category
    dict instead of a single `Decimal`; one pass, per category, oldest-first.
  - `member_account()` — `paid` and `total_tuition_paid` come off the
    per-category dict; adds the dues-bucket keys and `tuition_obligation`.
  - `accounts_overview()` — same per-category pots, so the two payment
    aggregates collapse into one `values("user", "payment_type")` query (total,
    tuition slice, last-payment date all fall out of it). One query fewer.
- Surfaces: treasurer member page gains a **Dues, all years** tile and a
  **Dues by year** table; Accounts roster gains a **Dues (all yrs)** column;
  balances CSV gains `dues_obligation` + `dues_balance`; the member's My LSP →
  Account tab gains the same all-years dues summary.
- No migration, no stored state, no backfill: coverage was always a read-time
  derivation. The next page render is correct.

## Verification

Prod, read-only, old and new coverage side by side over all 81 members with
ledger activity (via SSM — `ssh lsp` was timing out):

- **0 balance mismatches**, asserted from the raw inputs rather than from the
  sweep: `obligation` and `paid` are computed independently of coverage, so no
  coverage rule can move a balance. (Covered *totals* do drop for members
  holding cross-category surplus — that surplus now settles nothing — but that
  is the meta accounting, not the account.)
- 18 members have at least one charge re-attributed; 6 tuition-year counts
  change, all upward, none crossing the 4-year promotion gate.
- Post-deploy spot check on the reporting member's live account: balance
  $2,000 owed (unchanged), tuition 3 of 4 years, AY 2023–24 at $0/$2,000, all
  four dues years and all four registration charges reading paid.

**Shipped:** merged to `main` and deployed 2026-07-25 (`cd99279`); Deploy run
green.

## Tests

`payments/test_ledger.py`:

- `test_registration_money_never_covers_an_older_tuition_year` — the reported
  defect, minimally.
- `test_task_473_reported_account_shape` — Rico's prod account replayed
  charge-for-charge: $7,970 paid / $9,970 obligation / $2,000 balance
  (unchanged), 3 tuition years covered, the 2023 year at $0, every dues and
  registration charge reading paid.
- `test_tuition_years_covered_ignores_settled_other_category_money` and
  `test_surplus_in_another_category_never_advances_tuition_years` — the
  promotion gate, both with and without a matching charge.
- `test_dues_surplus_never_covers_tuition`,
  `test_payment_in_a_category_with_no_charges_covers_nothing` — no spillover.
- `test_dues_bucket_totals_and_rows`, `test_dues_bucket_on_accounts_overview`.
- `test_fungible_net_balance_across_categories` (unchanged from #439) still
  passes — the *account* is still fungible.

Consumers: `payments/test_ledger_consumers.py` gains
`test_dues_reminder_not_silenced_by_tuition_money`, and its
`test_dues_reminder_skips_ledger_covered_member` now uses dues money with no
`dues_period` FK (coverage, not the FK, is what decides).
`payments/test_audit_ledger.py`'s disagreement case moves to the same shape,
since a tuition payment can no longer produce a dues disagreement.
`payments/test_dues_lifecycle.py::test_dues_page_already_paid_despite_older_backfilled_debt`
uses a *dues* backlog, because only a same-category backlog can strand a
current-year dues payment — the `/dues/` FK-bound already-paid guard is still
needed. Render coverage in `formation/test_account_tab.py` and
`payments/test_treasurer_accounts.py`.
