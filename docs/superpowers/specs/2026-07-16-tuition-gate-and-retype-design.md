# Tuition clearance gate + payment re-categorize—design (task #439 follow-on)

**Date:** 2026-07-16
**Status:** Approved by Rico (brainstorming session)
**Builds on:** the unified member ledger (docs/superpowers/specs/2026-07-14-treasurer-unified-ledger-design.md) and the frozen-tuition-history rule (transitioning to Analyst/Scholar freezes tuition history; `payments/charges.py`).

## Problem

1. **Promotion can outrun the books.** A member can be promoted to Analyst/Scholar while tuition is still owed; the freeze then locks in the drift. The system must refuse the transition until tuition is settled—on every surface that can change a role.
2. **No treasurer re-categorize.** Payment categories can only be changed from the Reconcile queues (provisional/no-payer rows) or raw Django admin. The cleanup pass (mis-typed tuition payments: Garcia $5,850, Tod, Sheila) needs a first-class, audited re-type action.

## Decisions (settled with Rico, 2026-07-16)

1. **Gate rule:** promotion to Analyst/Scholar requires `tuition_years_covered == 4` AND no uncovered (unpaid/partial) tuition charge of any kind. These are **necessary but insufficient** conditions—completing the Passage/Traversée remains the Meeting of Analysts' decision; the gate is one criterion inside it, never a substitute for it.
2. **Coverage:** all role-change surfaces—the `record_membership_change` chokepoint, the Meeting's advancement flow, the Board membership admin, the Django admin role field (ProfileAdmin + User-page inline), and the CSV importer.
3. **Override:** none. The ledger is the override: resolve the named charges with the existing audited levers (record payment, adjust, waive, void), then promote.
4. **Re-type UI:** category select + dues-year/tuition-year binding, on both the Payments tab and the member statement. Donation flips allowed (treasurer-only counterpart to the member-side block).

## 1. Clearance predicate—one source of truth

`payments/ledger.py: tuition_clearance(user) -> list[str]`—empty list = clear to promote; otherwise human-readable reasons.

- Reason per non-void, non-waived tuition charge whose sweep state is not `paid`: "AY 2025–2026 tuition charge has $1,675 uncovered."
- Reason when `tuition_years_covered < TUITION_YEARS_REQUIRED`: "3 of 4 tuition years covered."
- Personas are exempt (return `[]`)—sandbox training flows must not be blocked.
- Reads pre-transition state; a member promoted through the gate therefore freezes a clean tuition history by construction.

## 2. Enforcement surfaces

- **Chokepoint (hard guarantee):** `accounts/membership.py: record_membership_change` raises `django.core.exceptions.ValidationError` (reasons as messages) when the target role is `analyst`/`scholar`, the member's CURRENT role is an in-training role, and `tuition_clearance` returns reasons. (Scoped to promotions out of training: bootstrap imports and Board records of externally-arriving Analysts—external→analyst with no tuition history—are not tuition transitions and pass freely.) Covers every caller, present and future. A shared helper `accounts/membership.py: validate_role_transition(user, new_role)` wraps the check for form consumers.
- **Meeting of Analysts advancement:** `formation/advancement.py: decide_advancement` checks clearance before approving; the `advancement_decide` view converts a block into a `messages.error` naming the reasons (never a 500). Proactively, the advancement **detail page gains a "Tuition standing" panel** (clear ✓, or the reasons list, with a link to the member's treasurer account page for staff who can see it) and the **advancement queue badges blocked rows**—the Meeting sees financial standing before voting.
- **Board membership admin:** `MembershipChangeForm.clean` calls `validate_role_transition` and re-raises as form errors.
- **Django admin:** ProfileAdmin's form and the User-page `ProfileInline` form validate `role` changes through the same helper—an admin edit to analyst/scholar with unsettled tuition is rejected with the reasons.
- **CSV importer (`import_users --update`):** a row that would elevate an existing member to analyst/scholar with clearance failing skips the `role` field (all other fields still apply), counts it, and reports each skip in the summary.
- **Block message convention:** name the exact charges and the fix path—"Resolve on the member's treasurer account page (record payment, adjust, waive, or void), then retry."

## 3. Payment re-categorize (treasurer)

POST `treasurer_payment_retype(payment_id)`, staff-gated, `next`-honoring:

- Fields: `payment_type` (any `Payment.Type`; no-op re-types refused with a message), and—when the new type is dues/tuition—an academic-year selector binding `dues_period`/`tuition_period` (defaults to the period containing the payment date, falling back to current).
- Side effects: append an audit note recording old→new type and old FK values (treasurer email, dated); set the matching period FK; clear category FKs that no longer apply (`dues_period` when leaving dues; `tuition_period` and `tuition_installment` when leaving tuition—the note records the unlinked installment); promote `source` to VERIFIED (treasurer-reviewed).
- Donation flips allowed—this is the deliberate treasurer-only override of the member-side donation block; it moves money into/out of the member's pot by design.
- UI: compact per-row "Re-categorize" disclosure form on the Payments tab rows and the member-statement payment rows.
- Interaction with frozen history: re-typing a transitioned member's tuition payment changes their tuition-paid sum and their frozen charges will NOT auto-adjust—the statement shows the result plainly and the treasurer follows up with adjust/void on the affected charge. Documented in the treasurer guide.

## 4. Testing

- Predicate: covered/waived → clear; partial/unpaid → reason; <4 years covered → reason; persona → clear; already-analyst no-op.
- Each surface: advancement decide blocked+unblocked (settle then retry), membership form error, admin form error, importer skip+report, chokepoint raise.
- Advancement detail panel renders standing; queue badge.
- Re-type: FK set/clear per direction, audit note content, donation flip allowed, no-op refused, `next` honored, ledger pot effect asserted.

## Out of scope / future

- **Member-initiated re-categorization across the donation boundary.** Members already re-type their own non-donation payments on the My LSP Money tab (`my_payments_update`); donation-crossing flips stay treasurer-only for now. Future direction (Rico, 2026-07-16): let members request any category change, with donation-crossing requests routed through a treasurer review/approval step rather than applying directly.
- Auto re-syncing a transitioned member's frozen tuition charges after a re-type (manual treasurer follow-up instead).
- Any change to the Passage/Traversée decision flow itself—the gate adds a criterion, nothing else.
