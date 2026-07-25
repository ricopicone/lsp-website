# Outstanding-Balance Runway + Manual Access Cutoff (Phase D) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After Nov 30, members with an outstanding ledger balance get a weekly reminder ladder; the treasurer sees who is past due and how often they've been reminded, and can manually (audited, reversibly) suspend a member's seminar-group access until the balance clears.

**Architecture:** One predicate — unified ledger balance > 0 past the current DuesPeriod's due date. `send_balance_reminders` (weekly, rides the dues cron) + `BalanceReminder` rows for throttling and the treasurer's "reminded N times" column. Suspension is a Profile flag flipped only by a treasurer action on the member account page; seminar Workgroups' derived rosters exclude flagged members. No automatic cutoff.

**Tech Stack:** Django 5.2, payments.ledger (member_account balance), ThrottledSender, pytest-django.

## Global Constraints

- Member-facing copy: commas, never em dashes. DaisyUI semantic tokens only.
- `uv run pytest -q` + `uv run ruff check .` green per commit; no push until plan done.
- Do-not-over-automate: the ONLY automated part is email; access changes are human actions logged for audit.
- Spec: `docs/superpowers/specs/2026-07-22-tuition-fall-launch-design.md` §D.

---

### Task 1: BalanceReminder + send_balance_reminders

**Files:**
- Modify: `payments/models.py` — `BalanceReminder(user FK related_name="balance_reminders", sent_at auto_now_add, balance DecimalField(max_digits=8, decimal_places=2))` + migration.
- Create: `payments/management/commands/send_balance_reminders.py` — gates: current `DuesPeriod` exists AND `today > due_date`, else exit quietly. For each active, non-persona member: compute the outstanding balance the same way the treasurer's Accounts view does (find and REUSE its helper in `payments/ledger.py` / `payments/views.py` — do not reimplement the sweep); skip balance <= 0; skip if a BalanceReminder within the last 7 days; send via ThrottledSender + record row.
- Create: `payments/templates/... or payments/emails.py` — `send_balance_reminder_email(user, balance)` following `payments/emails.py` house style (EmailMessage, Reply-To SUPPORT_EMAIL): subject "Your Lacanian School account balance", body: balance amount, one-line explanation (dues, tuition, or event fees past due), link `SITE_BASE_URL + Account tab URL` (reuse `_account_tab_url` logic — reverse("formation:formation") + "?tab=account"), support contact. Also a bell notification via the existing `DUES_REMINDER`-style pattern — add category `BALANCE_REMINDER = "balance_reminder", _("Balance reminders")` mirroring how DUES_REMINDER registers.
- Create: `payments/test_balance_reminders.py` — before due date: nothing; after: only positive-balance members emailed + row recorded with the amount; second run within 7 days silent; personas/inactive skipped; balance computation matches the treasurer view's number for a member with one unpaid charge.

- [ ] Failing tests → implement → suites green → commit `feat(payments): outstanding-balance reminder ladder (task #450 phase D)`.

### Task 2: Treasurer Owing columns

**Files:**
- Modify: the treasurer Accounts view (`payments/views.py:accounts_overview` area, the `owing` rows ~line 103) — each owing row gains `reminder_count` and `last_reminded` (aggregate over `BalanceReminder`, one query via annotation or a values map, not N+1).
- Modify: the Accounts tab template (grep for where the owing table renders) — two new columns, "Reminders" (count) and "Last reminded" (date or "never").
- Test: extend the existing accounts-overview tests (find them: `grep -rln accounts_overview payments/*test*`) — a member with two BalanceReminder rows shows count 2 and the latest date.

- [ ] Failing tests → implement → suites green → commit `feat(payments): Owing shows balance-reminder history (task #450 phase D)`.

### Task 3: Manual seminar-access suspension

**Files:**
- Modify: `accounts/models.py` — `Profile.seminar_access_suspended = models.BooleanField(default=False, help_text=...)` + migration.
- Modify: the seminar Workgroup derived-roster source: find where seminar rosters derive from registrants (`grep -rn "derived" workgroups/models.py events/` — the Event-attached workgroup's participants/active_members path) and exclude users whose profile has the flag, ONLY for the registrant-derived portion (faculty stay).
- Modify: treasurer member-account page (`payments/views.py` member_account + its template) — a "Suspend seminar group access" / "Restore access" toggle (POST, treasurer-gated like the page's other actions, requires a short reason, appends an audit note the way the page's other actions do — mirror the existing add/adjust/waive action pattern).
- Test: `payments/test_access_suspension.py` — flag excludes a paid registrant from the seminar workgroup roster (and their Parlêtre channel access via the workgroup, if roster-derived) while faculty remain; toggle POST flips flag + writes the audit note; non-treasurer 404.

- [ ] Failing tests → implement → suites green → commit `feat(accounts,payments,workgroups): manual seminar-access suspension for unpaid balances (task #450 phase D)`.

### Task 4: Controller steps (not a subagent)

- [ ] Final whole-branch review, fix wave, push, deploy green.
- [ ] Host: add `ExecStart=/usr/local/bin/lsp-web-exec python manage.py send_balance_reminders` to `lsp-dues-cron.service` (rides the weekly cron; self-guards until after the due date; cron timer itself still held for the Owing cleanup).
- [ ] Ledger + briefing updates.
