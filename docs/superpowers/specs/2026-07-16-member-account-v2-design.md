# Member Account v2—one tab, treasurer-parity edits, history submissions (task #439)

**Date:** 2026-07-16
**Status:** Approved by Rico (in-session)
**Builds on:** the unified ledger, the member Account tab (formation `_tab_account.html`), and the treasurer statement actions (retype/split/settle modals).

## Decisions (Rico, 2026-07-16)

1. **One tab, named "Account".** The Tuition tab is removed; its decision form and payment-plan/installment display move into the Account tab's top summary (tuition + dues side by side). The "My payments" editable table is removed from everywhere—its powers are subsumed by statement actions.
2. **Requirement-met split.** Two predicates with distinct semantics:
   - *Decision exemption* (enrollment-based, existing `tuition_requirement_met`, renamed `tuition_decision_exempt`): ≥4 non-skipping enrollments → no fifth-year decision nag (Gate 1, reminders, Undecided queue). Unchanged behavior.
   - *Requirement met* (payment-based, display + promotion): `tuition_years_covered >= 4`. The Account summary and any "Requirement met" badge use THIS. A member with 4 enrollments but 3 covered years shows "3 of 4 years paid" (and no decision nag). `tuition_clearance` (promotion gate) already uses covered years—unchanged.
3. **Member statement actions: full treasurer parity** on their OWN payments, including donation flips, with `source=SELF_REPORTED` and member-attributed audit notes. Concretely: re-categorize (with dues/tuition year binding = the AY-setting that "My payments" used to offer), settle-with-charge on re-categorize to Registration (historical event fees; the charge is `staff_adjusted=True`, `source=SELF_REPORTED`), and split across categories (donation parts allowed). Same system invariants as the treasurer: registration-settling payments refuse retype/split/assign-style changes; split rows can't be re-split; memberless guards are irrelevant (own payments only). Members do NOT get direct charge add/waive/void/adjust—charges enter via settle mechanics or the submission queue.
4. **History submission queue.** Members submit claims of missing historical payments or charges ("I paid $2,000 tuition in 2019"); the treasurer approves or declines from a queue. Crucial for students who started before records begin and haven't finished formation.

## 1. Tab consolidation

- `formation/tabs.py`: remove the `("tuition", "Tuition")` entry; rename the account tab label to "Account". Old `?tab=tuition` links fall back to the hub default gracefully.
- `_tab_account.html` top section becomes a two-column summary:
  - **Tuition**: years-paid progress (`tuition_years_covered` of 4; "Requirement met" badge only when covered ≥ 4), the current-year decision line (decision_label), the decision form (from `_tab_tuition.html`, verbatim behavior) when a decision is needed and not decision-exempt, the "no annual decision needed" notice when exempt, and the installments/plan block when one exists.
  - **Dues**: existing badge + pay flow.
- `_tab_tuition.html` and `_my_payments_table.html` are deleted once nothing references them; `my_payments_update` (the old bulk-edit endpoint) is retired—grep and remove its URL/tests, with behaviors re-tested through the new actions.

## 2. Member statement actions

- New member endpoints (own-payment scoping enforced, 404 otherwise): `my_payment_retype`, `my_payment_split`—mechanically mirrors of the treasurer versions (shared helpers `_apply_category_change`, `_unwind_installment`, `_parse_amount`, settle-charge mint) with: `source=SELF_REPORTED` on the payment; audit note "Re-categorized … by member {email}"; settle/split-minted charges `source=SELF_REPORTED, staff_adjusted=True`, note attributed to the member.
- Modal partials reused with a `next` back to the hub tab; the member statement's payment rows gain Re-categorize and Split buttons (+ the existing member_note editing moves into a small note modal writing `member_note`, replacing the old table's note column).
- Member re-categorize modal includes the dues-year/tuition-year selectors (conditional, as treasurer)—this IS the AY-setting feature.
- Refunds, receipts, assign: not member actions.
- Split rows: members may re-categorize their own split children (parity) but nothing re-splits a split row.

## 3. History submissions

- Model `payments.LedgerSubmission`: `user` FK; `kind` (PAYMENT/CHARGE); `category` (Payment.Type values for payments; dues/tuition/registration for charges); `amount`; `claimed_date` (date; for dues/tuition the matching AY period is derived date-window style); `details` (member text, required); `status` PENDING/APPROVED/DECLINED; `decision_note`; `decided_by`/`decided_at`; `created_payment`/`created_charge` nullable FKs; `created_at`.
- Member UI on the Account tab: "Report missing history" form (kind, category, amount, date, details) + a list of their submissions with status/decision note.
- Treasurer: a **Member submissions** section on the Reconcile tab (count also in the Overview attention queue): each row shows the claim + member, Approve/Decline with note. Approve mints, atomically:
  - PAYMENT → `Payment(status=SUCCEEDED, method=OFFLINE, source=SELF_REPORTED, paid_at=claimed_date noon, dues/tuition period bound by date for those categories)`, note "Member-reported history (submission #N), approved by treasurer {email}."
  - CHARGE → `Charge(status=OPEN, source=SELF_REPORTED, staff_adjusted=True, effective_date=claimed_date)`, same note convention.
- Decline records the note; nothing minted. Member is notified on decision via the notifications center (generic fallback email/bell); member-facing copy uses commas.
- The ledger recomputes automatically; no other machinery.

## 4. Testing

Predicate split (decision-exempt vs covered-met; Gate 1 regression stays enrollment-based); tab consolidation (no Tuition tab, decision form works inside Account, old behaviors retested); member retype/split/settle parity incl. donation flips and SELF_REPORTED provenance; own-payment scoping (404 on another member's payment); privacy regression (leakage test still green with new modals); submission lifecycle (create → queue renders → approve mints with correct provenance/period → decline notes → member list shows status); attention-queue count.

## Out of scope

Member charge add/waive/void/adjust; member refunds/receipts; auto-matching submissions to Stripe; editing submissions after decision.
