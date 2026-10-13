# Per-class billing (REG-6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A seminar can bill per class attended; existing whole-seminar billing, coverage, plans, codes, comps and removal are untouched.

**Architecture:** A per-class registration is a $0 PAID registration carrying `per_class_rate`. Attendance rows (`events.ClassAttendance`) are recorded after each class, corrected for 3 days, then billed as ordinary registration-category `Charge`s whose `registration` FK is NULL (linked via a new `class_attendance` FK), and paid by Payments linked via a new `per_class_registration` FK. Existing money paths key on `registration` and so never see these rows.

**Tech Stack:** Django 5.2, pytest-django, Stripe Checkout, Daily REST (`/meetings`).

**Spec:** `docs/superpowers/specs/2026-10-12-per-class-billing-design.md`

## Global Constraints

- Default `Event.billing_mode = "whole"`; no existing event changes behaviour.
- Member-facing copy: commas, not em dashes; says what, not why.
- Dates: `timezone.localdate()`, never `timezone.now().date()` (guarded by `core/test_local_dates.py`).
- New ModelForm fields with defaults: `required=False`, coerce in `clean_<field>`.
- Classes set from Python must also appear in a template (Tailwind scan).
- Every POST form already gets the submit-once guard; never use `disabled` on submitters.
- `send_meeting_reminders` hosts the new pass (no host timer change).
- Staff paths never retro-bill (the #485 rule).

## Review Focus

1. A covered per-class registrant records SKIPPING → classes bill at the per-class rate, and the whole-seminar re-bill does **not** touch the registration (test in Task 4).
2. Self-cancel of a converted registration that holds a $25 Stripe payment → status CANCELLED, **no refund issued** (Task 3).
3. The pass runs twice in one tick / two overlapping runs → one charge per class (constraint + `get_or_create`, Task 5).
4. A class ending 17:30 Pacific → charge `effective_date` is the Pacific date, not UTC (Task 5).
5. A registrant who registered after a class ended → no row for that class (Task 5).

---

### Task 1: Schema

**Files:** `events/models.py`, `registrations/models.py`, `payments/models.py`, `notifications/categories.py`, migrations in each app.

**Produces:**
- `Event.BillingMode` (`WHOLE="whole"`, `PER_CLASS="per_class"`), `Event.billing_mode` (default whole), `Event.per_class_since` (DateTimeField null), `Event.is_per_class` property.
- `EventProposal.billing_mode` (same choices, default whole).
- `Registration.per_class_rate` (Decimal null), `Registration.is_per_class` property (`per_class_rate is not None`).
- `events.ClassAttendance(registration FK CASCADE, session FK CASCADE, present bool, source choices detected/presumed/faculty/student, faculty_locked bool, marked_by FK null, recorded_at, billed_at null, outcome choices ""/charged/absent/covered/comped/no_charge, notified_at null, notes text)`; unique (registration, session).
- `Charge.class_attendance` FK(ClassAttendance, PROTECT, null, related_name="charges"); constraint `charge_unique_class_attendance` (non-void).
- `Payment.per_class_registration` FK(Registration, PROTECT, null, related_name="per_class_payments").
- Categories `CLASS_ATTENDANCE` ("Class attendance") and `CLASS_BILLING` ("Per-class bills"), SECTION_PAYMENTS.

Tests (`events/test_per_class_models.py`): default mode whole; `is_per_class`; attendance uniqueness; class charge constraint allows a void + a new one; a session with a billed attendance cannot be deleted (ProtectedError).

### Task 2: Price spec, forms, proposal, codes

**Files:** `events/price_spec.py`, `events/forms.py`, `events/models.py` (`_build_price_tier`), `events/templates/events/_price_fields.html`, proposal template.

**Produces:**
- `PriceSpec.per_class: bool = False` (in `to_dict`/`from_dict`; `from_event` reads `event.billing_mode`).
- `apply_to_event` sets `billing_mode` (+ `per_class_since=now` when switching on) and raises `BillingModeLocked(UnrepresentablePricing)` when the mode would change while `event.registrations` has an active row. `force=True` kwarg bypasses (conversion only).
- `label()` appends " per class".
- `PriceFieldsMixin.billing_mode` ChoiceField (required=False, coerced "whole").
- `EventProposalForm` carries `billing_mode`; `_build_price_tier` passes it.
- `PricingCodeForm(event=…)`: on a per-class event refuse `installments>1` and `FULL_PRICE`.

Tests (`events/test_per_class_pricing.py`): spec round-trip; label; lock raises with a registration, not without; proposal approve mints mode; change-request apply carries mode; code form refusals; existing price-spec tests unchanged.

### Task 3: Registration paths and the skip-list

**Files:** `registrations/views.py`, `registrations/services.py`, `registrations/models.py`, `payments/coverage.py`, templates `register_confirm.html`, `register.html`.

- `_create_registration`: if `event.is_per_class` → rate = `resolution.amount`, `quoted_amount=0`, status PAID (or PENDING_APPROVAL), never build a plan; explanation "Per class: $X per class attended."
- Resolve the rate with coverage ignored: `resolve_price(..., ignore_tuition=True)` (new kwarg, default False).
- Covered short-circuit on a per-class event: rate = `coverage.retro_amount(tier)`.
- `apply_code` view: per-class PAID registration → `services.apply_per_class_code(reg, code, resolution)` (sets rate, consumes use, refuses installments>1).
- `pinned_code_for` / `auto_apply_pinned_code`: per-class branch applies a lower rate.
- `Registration.cancel()`: per-class → never refund (treated as refund=False).
- `comp_registration`: also accepts PAID per-class → COMPED (no comped charge; quoted is 0).
- `remove_registration`: per-class → no refund attempted; `left_money` 0.
- `coverage.covered_registrations` / `apply_coverage`: `.filter(per_class_rate__isnull=True)`.

Tests (`registrations/test_per_class_registration.py`): register fixed / sliding / with code / covered member / approval; installments code refused; cancel of a converted reg (a $25 Stripe payment on `reg.payments`) issues no refund; comp; removal; skipping re-bill and apply_coverage ignore per-class; pinned lower-rate code auto-applies.

### Task 4: Ledger helper, billing core, coverage hooks

**Files:** create `events/per_class.py`; modify `payments/ledger.py`, `payments/views.py` (tuition decision wiring), `payments/templates/payments/skip_confirm.html`.

**Produces (in `events/per_class.py`):**
- `WINDOW = timedelta(hours=72)`, `CORRECTION_DAYS = 14`, `DETECT_RETRY = timedelta(hours=24)`.
- `is_covered(reg) -> bool` (tier covered, no code, tuition-current for event AY).
- `bill(att, *, now) -> Charge | None` — idempotent; sets outcome/billed_at.
- `open_charges(reg) -> list[(Charge, Decimal remaining)]`, `open_balance(reg) -> Decimal` via `ledger.charge_coverage(user)`.
- `can_void(att, *, today) -> bool`; `mark(att, *, present, by, role)` handling window/lock/post-billing rules.
- `void_covered_open(user, period) -> list[Charge]`; `bill_covered_classes(user, period) -> list[Charge]`; `covered_classes(user, period)` for the skip interstitial.

`payments/ledger.py`: `charge_coverage(user) -> (states, covered_by_id, charges)`; `member_account` uses it.

Wiring: member tuition decision — skipping also `bill_covered_classes`; covering also `void_covered_open`. Treasurer set-status covering → `void_covered_open` (silent).

Tests (`events/test_per_class_billing.py`): bill present → charge with Pacific effective date, registration NULL; absent/comped/covered/zero → no charge; idempotent; open_balance uses ledger (credit sweeps); can_void on open vs partially paid vs >14 days; faculty lock; student can't change after window; coverage hooks both directions; staff path never bills.

### Task 5: Recording pass, Daily detection, notices

**Files:** `events/per_class.py`, `video/daily.py` (`list_meetings`), `video/services.py` (`mint_token` user_id), `workgroups/management/commands/send_meeting_reminders.py`, `events/notifications.py` or `payments/notifications.py`, email templates.

- `daily.create_meeting_token(user_id=…)`; `mint_token` passes `str(user.pk)`.
- `daily.list_meetings(room_name, start_ts, end_ts) -> list[dict]`.
- `per_class.detect_present(session) -> set[int] | None` (None = can't detect / failed).
- `per_class.record_session(session, *, now) -> list[ClassAttendance] | None` (None = retry later).
- `per_class.run(now) -> dict` — record due sessions, bill closed windows, weekly notices (Monday ≥ 09:00 school time; per (user, event) for charged rows with `notified_at` null).
- Command gains `_per_class(now, dry)`.

Tests: detection path with mocked Daily; failure retries then presumes; hybrid/in-person presumed; late registrant skipped; sessions before `per_class_since` skipped; weekly notice only Monday, once; notices to leads + registrants.

### Task 6: Payment and statements

**Files:** `payments/stripe_checkout.py` (`create_per_class_session(reg)`), `payments/stripe_sync.py` (`expire_open_sessions` covers `per_class_payments`), `registrations/views.py` (`pay_classes` view + url), statement templates (treasurer member page + member Account tab).

Tests: pay view mints Payment(per_class_registration=reg, registration=None, amount=open balance); refuses 0; complete_payment issues receipt only and the reg stays PAID; ledger balance goes to 0; statement labels render class lines.

### Task 7: UI

**Files:** `events/views_per_class.py` (mark views) + urls; `events/templates/events/_class_attendance.html` (faculty section, included in `_faculty_tools.html`); `events/templates/events/_your_classes.html` (member panel, included in `_event_summary.html` and Workspace overview); price label on event page + register page copy.

Tests: faculty sees section only on per-class events; member marks self in window; non-lead forbidden; the POST paths enforce `mark` rules.

### Task 8: Conversion command

**Files:** `events/management/commands/convert_event_to_per_class.py`.

`--price` ("25" fixed or "10-40" sliding), `--bill-from YYYY-MM-DD`, `--dry-run`. Refuses plans / installment codes. Per reg: rate via existing code (ignore coverage), quoted 0, void whole-seminar charge, staff note, notice.

Tests on a fixture shaped like event 25.

### Task 9: Docs

Faculty guide per-class section, treasurer + registrar guide paragraphs, CLAUDE.md status entry.
