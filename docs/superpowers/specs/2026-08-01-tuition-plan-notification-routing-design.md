# Tuition payment-plan notifications: route email to the Treasurer

Task #491. 2026-08-01.

## Problem

Every tuition payment-plan application emails every active Board member.

A member applies from the Account tab (`TuitionDecisionForm`, "I want to apply
to the Board for a payment plan" + required reasons). That creates a
`TuitionPlanApplication` (PENDING) and calls
`payments.notifications.notify_plan_application_submitted`, which loops over the
Board's active roster and raises a `TUITION_PLAN_REVIEW` notification for each.
That category defaults to *immediate* email, so each application emails the
whole Board. A Board member asked that this reach the Treasurer instead.

Two things are true and both matter:

- The Board genuinely owns the **decision** — the queue at
  `/admin-tools/tuition-plans/` is where approve/decline happens, and that
  should not move.
- The per-application **email** to every Board member is the actual complaint.

Related confusion, resolved separately below: "tuition assistance" and "payment
plan" are the same thing. The Tuition Assistance document still describes them
as two processes, one of them an email exchange that the site replaced.

## Design

### 1. Role-sensitive category default

`CategoryMeta` gains an optional callable:

```python
default_email_for: Callable[[User], str] | None = None
```

`notifications.preferences.resolve()` consults it in place of
`meta.default_email` when — and only when — the member has no explicit override
for that category. Existing categories leave it `None` and behave exactly as
before.

`TUITION_PLAN_REVIEW` sets it to: *immediate* when the member is an explicit
holder of `StaffRole.TREASURER`, *off* otherwise. `core.access.has_staff_role`
is explicit-holders-only (it does not implicitly include superusers), which is
the semantics we want — a superuser shouldn't silently start receiving
treasurer mail. The import lives inside the callable so `categories.py` keeps no
module-level dependency on `core.models`.

Result:

| Recipient | Bell | Email |
|---|---|---|
| Treasurer | yes | yes, immediate |
| Other Board members | yes | no |

Both remain adjustable at `/notifications/settings/`: a Board member who wants
the mail can set the row to *Email me* or *In a digest*, and the Treasurer can
turn theirs off. Because `resolve()` is the single source of truth for both
`notify()` and the settings page, the page shows each member their true
effective value rather than a static category default.

**Fallback.** If nobody holds the Treasurer role, the callable returns
*immediate* for everyone. An unassigned role must never mean an application
sits unseen.

### 2. Split the double-duty category

`TUITION_PLAN_REVIEW` is currently used for both the reviewer queue and the
applicant's decision notice (`notify_plan_application_decided`). Defaulting the
reviewer side to *off* would therefore also stop applicants hearing their own
outcome.

Add `TUITION_PLAN_DECISION` ("Your payment plan application", section
Registration & payments, email *immediate*) and move
`notify_plan_application_decided` onto it. `TUITION_PLAN_REVIEW` becomes
reviewer-only; its help text changes to name the Treasurer and Board.

No data migration. `Notification.category` on already-sent rows only affects
delivery routing at send time, and those rows are already delivered — unlike
`Notification.url`, which is denormalized into the row and does need migrating
when a link builder changes.

### 3. Queue access

Unchanged. `payments/views_plan_review.py::_can_review` gates on superuser or
active Board membership; the Treasurer is always on the Board, so no additional
role check is needed.

## Tuition Assistance document

Rewrite the body via a new `documents` data migration (following
`0011_tuition_assistance_account_tab`), same shape as its predecessors:
`RunPython` setting `Document.body` for slug `tuition-assistance`, reverse
`noop`.

Content changes:

- Tuition assistance **is** the payment plan. The document stops presenting
  them as two processes.
- Drop the email-the-Treasurer procedure and the "symbolic contribution"
  language. The Board does not grant reduced totals; an approved plan is the
  full annual amount spread across installments.
- Describe what the site does: apply from the Account tab with your reasons,
  the Board reviews and decides, you're notified of the decision, and on
  approval you choose 2 installments (September and February) or 9 (monthly,
  September through May).
- Keep: skipping a year, the four-non-consecutive-years rule, reminders, the
  member's own record-keeping, and reporting a pre-website payment.
- Correct the stale "no special authorization is needed to pay in
  installments" line — Board approval is exactly what is now needed.
- House style for member-facing copy: commas, not em dashes.

## Testing

- Treasurer holder gets a bell row and an immediate email on submission.
- A Board member who is not the Treasurer gets a bell row and no email.
- An explicit preference override wins in both directions: a Board member set
  to *Email me* is emailed; a Treasurer set to *No email* is not.
- With no Treasurer role holder, Board members are emailed (fallback).
- The applicant is excluded from the reviewer notification (existing behaviour,
  pin it).
- The decision notice emails the applicant even when their
  `TUITION_PLAN_REVIEW` is off, proving the split.
- The settings page shows a Treasurer *Email me* and a non-Treasurer Board
  member *No email* for the same untouched category.
- Categories with no `default_email_for` resolve exactly as before.

## Out of scope

- Moving where the decision is made. The Board keeps the queue.
- Any reduced-tuition or waiver mechanism (no such thing exists in the ledger,
  and per this task none is wanted).
- A general admin-side "who receives this queue" routing layer. Every queue
  notification in the app is already per-category adjustable by its recipient;
  this task adds role-sensitive *defaults*, which is the piece that was
  missing.
