# Member Account v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One member "Account" tab (Tuition tab folded in, My-payments table retired), treasurer-parity statement actions for members (retype/split/settle/AY, SELF_REPORTED), the requirement-met predicate split (decision-exempt vs paid), and a member→treasurer history-submission queue.

**Architecture:** Spec: `docs/superpowers/specs/2026-07-16-member-account-v2-design.md`. Member endpoints mirror the treasurer's via the shared helpers in `payments/views.py` (`_apply_category_change`, `_unwind_installment`, `_parse_amount`, `_safe_next`) and `payments/ledger.py`. New model `payments.LedgerSubmission`. Existing precedents to mirror are named per task — read them before writing.

**Tech Stack:** Django 5.2, pytest-django, DaisyUI v5.

## Global Constraints

- Worktree only: `/Users/picone/LSP-Web-Coordinator/lsp-website/.claude-worktrees/eager-falcon`. Never the main repo path.
- `uv run pytest <files> -q` per task; full `uv run pytest -q` + `uv run ruff check .` green before every commit.
- MEMBER-SAFETY: member-facing templates never render `Payment.notes`, `Charge.notes`, `source`, or provenance. The double-sided leakage test (`formation/test_account_tab.py`) must stay green; extend it when adding member modals.
- Member writes: own payments only (`user=request.user` scoping → 404 otherwise); `source=SELF_REPORTED`; audit notes attributed "by member {email}"; member-minted charges `staff_adjusted=True, source=SELF_REPORTED`.
- System invariants unchanged: registration-settling payments refuse retype/split; split rows never re-split; money is Decimal; `_parse_amount` bounds all amounts.
- Member-facing copy: commas, not em dashes. DaisyUI semantic tokens only.
- Commit per task: `feat(...): … (task #439)`.

---

### Task 1: Predicate split — decision-exempt vs requirement-met(paid)

**Files:** `payments/ledger.py`, callers (`registrations/views.py`, `payments/views.py` `_attention_queue`, `payments/management/commands/send_tuition_reminders.py`), `formation/views.py` + `formation/templates/formation/_tab_account.html`, tests (`payments/test_member_account_actions.py::test_requirement_met_members_need_no_new_year_decision` adapt-rename, `formation/test_account_tab.py`).

**Interfaces:**
- Rename `ledger.tuition_requirement_met` → `ledger.tuition_decision_exempt` (semantics unchanged: ≥4 non-skipping enrollments). Update the three enforcement callers + docstrings ("no fifth-year decision nag").
- Display "Requirement met" everywhere = `acct["tuition_years_covered"] >= acct["tuition_years_required"]` (payment-based). Account tile + tuition summary: show "N of 4 years paid"; the badge only when covered ≥ 4; a separate quiet note "No annual tuition decision is needed" when decision-exempt but not covered-met.
- TDD the Rico case: 4 non-skipping enrollments, payments covering 3 → tile shows "3 of 4", NO "Requirement met" badge, decision form absent (exempt), Gate 1 still passes (`_tuition_block_reason` None).

- [ ] Failing tests → RED → implement → GREEN → commit `fix(payments): requirement-met is payment-based; decision exemption stays enrollment-based (task #439)`.

---

### Task 2: Member statement endpoints — retype, split, note

**Files:** `payments/views.py` (new `my_payment_retype`, `my_payment_split`, `my_payment_note`), `config/urls.py`, `payments/test_my_payment_actions.py`.

**Interfaces:**
- `my_payment_retype(request, payment_id)`: mirrors `treasurer_payment_retype` EXACTLY (read it first; share every helper) with these deltas: payment fetched via `get_object_or_404(Payment, pk=…, user=request.user)`; NO donation-flip block (full parity — Rico 2026-07-16); `payment.source = Source.SELF_REPORTED`; audit note "Re-categorized {old} → {new} by member {email}."; settle-charge mint allowed (charge `source=SELF_REPORTED, staff_adjusted=True`, note "… inserted with re-categorization … by member {email} — the original event fee was never recorded."); split rows ARE editable (own-payments parity) — but registration-settling refusal stays; `_safe_next` fallback: the hub Account tab URL (find how formation builds `?tab=account` URLs — mirror `_tuition_tab_url` if present).
- `my_payment_split(request, payment_id)`: mirrors `treasurer_payment_split` with the same deltas (donation parts allowed; children `source=SELF_REPORTED`; notes attributed to the member; no re-split of split rows; registration-linked refuse; succeeded-only).
- `my_payment_note(request, payment_id)`: writes `member_note` (strip, cap 1000 — same cap as the old my_payments_update), replaces prior member_note (NOT append — member_note is the member's own editable field, matching old behavior).
- Old `my_payments_update` is retired in Task 3 — here just build the new endpoints. Tests: donation flip now applies with SELF_REPORTED; other-member's payment → 404; registration-linked refuse; split child retype allowed; settle mints member-attributed charge; note round-trip; AY binding via posted dues_period/tuition_period ids (this replaces the old table's AY column).

- [ ] TDD → commit `feat(payments): member statement actions — retype, split, settle, note (task #439)`.

---

### Task 3: Account tab consolidation

**Files:** `formation/tabs.py`, `formation/views.py`, `formation/templates/formation/_tab_account.html`, delete `_tab_tuition.html` + `_my_payments_table.html`, member modal partials (new `payments/templates/payments/member/_retype_modal.html`, `_split_modal.html`, `_note_modal.html` — copy the treasurer partials, point at the `my_*` URLs, STRIP anything member-unsafe: no provenance, no treasurer wording), `formation/test_account_tab.py` (+ adapt `formation/test_formation.py`, `payments/test_payments_hub.py` etc. — grep `tab=tuition`, `my_payments_update`, `_my_payments_table`).

**Interfaces:**
- Tab list: remove `("tuition", "Tuition")`; label the account tab "Account". `?tab=tuition` links: the hub's unknown-tab fallback must land somewhere sane (read the hub view; if unknown tabs 404/KeyError, map "tuition" → "account" explicitly).
- `_tab_account.html`: top becomes the two-column Tuition/Dues summary per the spec (move the decision form + installments block from `_tab_tuition.html` verbatim — same endpoint/fields; show the form only when a decision is needed AND not decision-exempt; requirement-met badge per Task 1). Statement payment rows gain the three member modal buttons (icons per the treasurer convention: tag/split/sticky-note — `{% load parletre_tags %}`). Remove the `_my_payments_table.html` include; delete both dead templates once unreferenced.
- `my_payments_update` view + URL retired: grep callers/tests; the behaviors (type change, note, AY) are re-tested through Task 2's endpoints — port any test INTENT that isn't already covered (e.g., cross-user protection) into `payments/test_my_payment_actions.py` before deleting old tests.
- Extend the leakage test to the new modals (plant markers, assert absent).

- [ ] TDD → full suite → commit `feat(formation): one Account tab — tuition folded in, statement actions, My-payments retired (task #439)`.

---

### Task 4: LedgerSubmission model + member form

**Files:** `payments/models.py` (+migration), `payments/views.py` (`my_ledger_submission_create`), `config/urls.py`, Account tab section, `payments/test_ledger_submissions.py`.

**Interfaces:**
- Model per spec §3: `LedgerSubmission(user, kind{payment,charge}, category (CharField using Payment.Type choices), amount, claimed_date, details TextField, status{pending,approved,declined} default pending, decision_note, decided_by FK null, decided_at null, created_payment FK null, created_charge FK null, created_at)`. `Meta.ordering = ("-created_at",)`.
- Member endpoint: POST kind/category/amount (via `_parse_amount`)/claimed_date (ISO; reject future dates)/details (required, cap 2000) → create PENDING; message. Account tab gains a "Report missing history" disclosure form + a compact list of the member's submissions (status badges + decision_note when decided). Member-safe: shows only their own fields.
- Tests: create validations (amount bounds, future date, empty details), list renders, member sees only their own.

- [ ] TDD → commit `feat(payments): member history submissions — model + report form (task #439)`.

---

### Task 5: Treasurer submissions queue

**Files:** `payments/views.py` (`treasurer_reconcile` context + `treasurer_submission_decide`), `payments/templates/payments/treasurer/reconcile.html`, `_attention_queue`, overview template line, `config/urls.py`, notifications wiring, `payments/test_ledger_submissions.py` (extend).

**Interfaces:**
- Reconcile tab gains a "Member submissions" section (PENDING rows: member link, kind/category/amount/claimed_date/details, Approve + Decline buttons with a shared note input; confirm dialogs). `_attention_queue` gains `submission_count` (PENDING count) + an Overview queue line linking to Reconcile.
- `treasurer_submission_decide(request, submission_id)` POST `decision` approve|decline, `note`: atomic; approve mints per spec §3 (payment: SUCCEEDED/OFFLINE/SELF_REPORTED, `paid_at` = claimed_date at noon UTC-aware, dues/tuition period bound date-window style via `_period_for`; charge: OPEN/SELF_REPORTED/staff_adjusted=True/effective_date=claimed_date) with the note convention "Member-reported history (submission #N), approved by treasurer {email}."; sets status/decided_by/at/decision_note + links created row. Decline just records. Idempotent guard: already-decided → message, no change.
- Notify the member on decision: read `notifications/dispatch.py` `notify()`'s signature + an existing simple caller (grep `dispatch.notify(`) and mirror the generic-fallback pattern; category: pick the closest existing generic category rather than inventing one (read `notifications/categories.py`; if nothing fits, use the pattern other apps use for one-off notices). Member-facing copy commas-only.
- Tests: approve-payment mints with provenance/period and the ledger reflects it; approve-charge mints; decline; idempotency; queue renders; attention count.

- [ ] TDD → commit `feat(treasurer): member-submission approval queue (task #439)`.

---

### Task 6: Docs + final verification

- Treasurer guide: submissions queue section (Reconcile), member statement powers note (they can re-categorize/split their own payments with member-reported provenance — the provenance popover shows who did what), requirement-met wording ("paid in full across four years"). Member help/copy already inline.
- CLAUDE.md: one status bullet.
- Full `uv run pytest -q` + `uv run ruff check .`; commit `docs(treasurer): guide + status for member account v2 (task #439)`.

## Deploy runbook
Push → Deploy green. No data migration beyond the new table; no backfill.
