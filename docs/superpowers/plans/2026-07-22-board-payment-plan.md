# Board Payment-Plan Application (Phase B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The "payment plan" tuition decision becomes an application to the Board: member states reasons, Board approves/declines from a queue, enrollment status tracks the outcome.

**Architecture:** New `TuitionEnrollment.Status.PLAN_REQUESTED` (non-covering) keeps the gate's single source of truth; a `TuitionPlanApplication` row carries reasons + decision + audit; a Board-gated queue at `/admin-tools/tuition-plans/` decides; notifications ride a new `TUITION_PLAN_REVIEW` category. Folds in four accepted minors from the A+C review: `TuitionPeriod.upcoming()` helper, invalid-slug fallback test, pay-in-full/plan flows accepting the upcoming period, and a date-order `clean()` guard.

**Tech Stack:** Django 5.2, pytest-django, notifications.dispatch.notify, DaisyUI templates.

## Global Constraints

- Member-facing copy: commas, never em dashes. DaisyUI semantic tokens only.
- `uv run pytest -q` and `uv run ruff check .` green before every commit. Do not push until the whole plan is done.
- Do-not-over-automate: Board decision is always a human action; treasurer admin overrides remain.
- Spec: `docs/superpowers/specs/2026-07-22-tuition-fall-launch-design.md` §B.
- A pending application counts as "a decision on file" (unlocks general registration) but never confers coverage.

---

### Task 1: Models — PLAN_REQUESTED, TuitionPlanApplication, upcoming(), clean()

**Files:**
- Modify: `payments/models.py` (TuitionEnrollment.Status, TuitionPeriod; new model after TuitionEnrollment)
- Create: migration via makemigrations
- Create: `payments/test_plan_application_models.py`

**Interfaces (produces):**
- `TuitionEnrollment.Status.PLAN_REQUESTED = "plan_requested", "Payment plan requested"` — `covers_seminars` stays False for it (assert: not in the covering set).
- `TuitionPeriod.upcoming()` classmethod: earliest period with `start_date > today`, or None.
- `TuitionPeriod.clean()` raises ValidationError when `payment_due_date` is set and earlier than `decision_due_date`.
- `TuitionPlanApplication(user FK, tuition_period FK, reasons TextField, status PENDING/APPROVED/DECLINED (TextChoices), created_at auto, decided_by FK null accounts.User related_name="+", decided_at null, note TextField blank)`; `Meta.constraints`: UniqueConstraint(fields=["user", "tuition_period"], condition=Q(status="pending"), name="one_pending_plan_application").

- [ ] Failing tests: PLAN_REQUESTED exists and `covers_seminars` is False for it; `upcoming()` returns the earliest future period and None with no future rows; `clean()` rejects payment_due < decision_due; second PENDING application for same user+period raises IntegrityError while a DECLINED + new PENDING pair is allowed.
- [ ] Implement; `uv run python manage.py makemigrations payments`; suites green; commit `feat(payments): PLAN_REQUESTED status, TuitionPlanApplication, TuitionPeriod.upcoming()/clean() (task #450 phase B)`.

### Task 2: Notification category + wrappers

**Files:**
- Modify: `notifications/categories.py` (new `TUITION_PLAN_REVIEW = "tuition_plan_review", _("Tuition payment plans")` in the payments block; read the file top-to-bottom first and mirror EXACTLY how existing categories register — including any CATEGORY_META/default-preference structure and data migration the module's conventions require).
- Modify: `payments/notifications.py` — three wrappers following the module's existing style: `notify_plan_application_submitted(application)` (to every Board reviewer: Board committee `active_members()`, excluding the applicant), `notify_plan_application_decided(application)` (to the applicant, approved/declined wording), each via `notifications.dispatch.notify(...)` with in-app + email like neighboring wrappers.
- Test: `payments/test_plan_application_models.py` (extend) — submitting creates bell rows for board members; deciding notifies the applicant.

- [ ] Failing tests → implement → suites green → commit `feat(payments,notifications): tuition plan application notifications (task #450 phase B)`.

### Task 3: Decision flow — apply with reasons

**Files:**
- Modify: `payments/forms.py:TuitionDecisionForm` — the `payment_plan` choice label becomes "I want to apply to the Board for a payment plan."; add `reasons = forms.CharField(required=False, widget=forms.Textarea)`; `clean()` requires non-blank reasons when status == "payment_plan".
- Modify: `payments/views.py:tuition_decision` — replace the ad-hoc upcoming query with `TuitionPeriod.upcoming()`; when status == "payment_plan": inside the atomic block set enrollment status to `PLAN_REQUESTED` (not PAYMENT_PLAN), `get_or_create` a PENDING `TuitionPlanApplication` (update reasons on re-submit while still pending), and call `notify_plan_application_submitted`. Other statuses unchanged.
- Modify: `formation/views.py` — use `TuitionPeriod.upcoming()` (kills the duplicate query); context includes each block's pending application state.
- Modify: `formation/templates/formation/_tab_account.html` — the payment-plan radio reveals a reasons textarea (plain, `class="textarea textarea-bordered w-full"`, progressive disclosure fine via checked state or always-visible with helper text); a PLAN_REQUESTED enrollment renders "Your payment plan application is with the Board." instead of the form.
- Test: `payments/test_tuition_decision_periods.py` (extend): payment_plan POST with blank reasons re-renders with error (or message) and writes nothing; with reasons creates PLAN_REQUESTED + PENDING application; invalid `period` slug falls back to the current period (the accepted-minor test); PLAN_REQUESTED member is NOT blocked by `_tuition_block_reason` for a plain seminar but gets no coverage from `_find_covered_tier`.

- [ ] Failing tests → implement → suites green → commit `feat(payments,formation): tuition payment plan is a Board application (task #450 phase B)`.

### Task 4: Board review queue

**Files:**
- Create: `payments/views_plan_review.py` — `tuition_plan_queue(request)` (GET list: pending first, then decided history) and `tuition_plan_decide(request, pk)` (POST `action=approve|decline`, optional `note`). Gate both: superuser OR active Board member (`Committee.objects.filter(slug="board").first()`, its `.active_members()`); anonymous → `core.access.gate_or_login(request)` redirect pattern; signed-in non-Board → 404 (site convention).
- Approve: application → APPROVED (+decided_by/at/note); enrollment for that user+period → PAYMENT_PLAN; notify applicant. Decline: application → DECLINED; delete the PLAN_REQUESTED enrollment row if it is still PLAN_REQUESTED (revert to no-decision); notify applicant. Both atomic, both idempotent-guarded (only a PENDING application can be decided).
- Create: `payments/templates/payments/tuition_plan_queue.html` — DaisyUI table: member, period, reasons (pre-wrap), created, approve/decline buttons with a note input; decided section below with outcome badges.
- Modify: `config/urls.py` — `path("admin-tools/tuition-plans/", ...)` + decide path, names `tuition_plan_queue` / `tuition_plan_decide`.
- Modify: the admin-tools index/nav where other consoles register (grep `admin-tools` templates — follow how referrals/applications appear) so Board members can find it.
- Test: `payments/test_plan_review_queue.py` — non-board 404, anon redirected to login, board member sees pending row, approve flips enrollment to PAYMENT_PLAN + notifies, decline deletes the enrollment + notifies, deciding twice is a no-op error.

- [ ] Failing tests → implement → suites green → commit `feat(payments): Board tuition payment-plan review queue (task #450 phase B)`.

### Task 5: Pay-in-full and plan setup honor the upcoming period

**Files:**
- Modify: `payments/views.py:tuition_pay_in_full` (~2236) and the installment plan-setup view (~2278): accept the same optional POST `period` slug validated against `{TuitionPeriod.current(), TuitionPeriod.upcoming()}` (fallback current — mirror `tuition_decision`); all downstream objects (installment, payment, checkout metadata) bind to the chosen period. Read `payments/stripe_checkout.py` far enough to confirm the period rides on the enrollment/installment, not re-derived from current().
- Modify: `formation/templates/formation/_tab_account.html` — the upcoming block's COMMITTED state offers the same "Pay in full" button with `<input type="hidden" name="period" value="{{ upcoming_period.slug }}">`.
- Test: `payments/test_tuition_decision_periods.py` (extend) — a COMMITTED-for-upcoming member POSTing pay-in-full with the upcoming slug gets an installment+payment bound to the upcoming period, not the current one.

- [ ] Failing tests → implement → suites green → commit `feat(payments): pay-in-full and plan setup accept the upcoming period (task #450 phase B)`.

### Task 6: Controller steps (not a subagent)

- [ ] Final whole-branch review (fresh reviewer, package from plan-start commit), fix wave if needed, push to main, deploy green.
- [ ] Prod: update the Tuition Assistance Document (documents app, inline HTML body — fetch current body first, then apply an edit adding the Board-application process and the Oct 31 / Nov 30 dates; commas not em dashes).
- [ ] Prod verify: queue page 404s for non-board, renders for rico; a test PLAN_REQUESTED round-trip on a persona if available.
- [ ] Ledger + briefing updates.
