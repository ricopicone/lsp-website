# Treasurer Admin Guide

*A walk-through of `/treasurer/` for whoever is acting as treasurer.
You should never need to use the underlying Django admin (`/admin/`)
for routine work — everything here lives in the treasurer admin.*

*If you also help with the academic program, see the
[Program Committee Admin Guide](/program-admin/help/).*

---

## How to get there

1. Log in at <https://app.lacanschool.org/> with your treasurer account.
2. Click your photo / initials in the top-right.
3. Pick **Treasurer dashboard** from the dropdown.

You'll land on the **Overview** tab. Eight tabs across the top:

| Tab | What it's for |
|---|---|
| **Overview** | At-a-glance snapshot of dues + tuition for the current academic year |
| **Tuition** | Per-student tuition status for in-training members (pre-candidates, candidates) |
| **Dues** | Per-member dues status with charts and per-period totals |
| **Members** | Look up any member to see their full payment history |
| **Payments** | Chronological list of all payments with refund / mark-paid controls |
| **Settings** | Edit dues + tuition amounts and reminder cadence per academic year |
| **Exports** | Download CSVs of payment data |
| **Help** | This page |

---

## Overview tab

A two-card summary of the current academic year:

- **Dues card**: the three tier amounts (pre-candidate / candidate /
  analyst), how many members are dues-obligated, how many have paid,
  how much has been collected.
- **Tuition card**: the annual tuition amount, how many in-training
  students are owed, the **reconciliation queue size** (students who
  need your attention), and how much tuition has been collected.

Use this to see at a glance whether anything needs work. If the
reconciliation queue is non-zero, open the Tuition tab.

---

## Tuition tab

Tuition is **per-academic-year** for in-training students (the four
"learning" roles: Pre-Candidate Analyst, Candidate Analyst,
Pre-Candidate Scholar, Candidate Scholar). Each year, each student
records one of these decisions:

| Decision | Meaning |
|---|---|
| **Committed** | "I plan to pay this year" — but no payment received yet |
| **Payment plan** | "I want to pay in installments" — plan is set up |
| **Paid in full** | The annual tuition has been received |
| **Exempt** | You've waived tuition for this student this year |
| **Skipping** | "I'm not paying tuition this year" (pays regular event fees) |

A full reference for the policy (including how it interacts with event
registration) lives in `LSP-Website-Tuition-Policy.md` in the
project's planning folder.

### Sections on the Tuition tab

- **Current period summary** — top-of-page cards: in-training count,
  collected total, **reconciliation queue size**.
- **Status breakdown** — small-card grid showing how many students are
  in each status, including "Undecided" (no enrollment row recorded).
- **By role** — per-role table: total in role, how many decided, how
  many undecided, how many committed-but-unpaid.
- **Reconciliation queue** — the rows you should look at. These are
  either **undecided** or **committed without payment**. Each row has
  three action buttons:
    - **Record payment** — records an offline tuition payment for the
      annual amount, marks the enrollment Paid in Full, and sends the
      student a receipt + confirmation email. Use this when you've
      received their cash / check.
    - **Skipping** — sets the student's status to Skipping (their
      explicit "I'm not paying this year"). They'll still pay regular
      fees for any events.
    - **Exempt** — you're waiving tuition for this student this year.
      Equivalent to Paid in Full for visibility purposes, but with no
      money received.

> All actions are recorded in the enrollment's notes field with the
> date and your email, so there's an audit trail.

### Common tuition workflows

- **"A candidate just paid me $800 in cash for this year."**
  → Tuition tab → find them in the reconciliation queue → click
  **Record payment**. Done. They get an email receipt.
- **"A candidate told me they want to do a payment plan."**
  → Tell them to go to `/tuition/` themselves and pick "I want to set
  up a payment plan", then choose 2 or 9 installments. They can pay
  each installment via Stripe.
- **"A candidate is skipping this year."**
  → Tuition tab → find them → click **Skipping**.
- **"This candidate is on a hardship waiver."**
  → Tuition tab → find them → click **Exempt**.

---

## Dues tab

Dues are **per-academic-year** and **tiered by role**:

| Role | Default annual dues |
|---|---|
| Pre-candidate (analyst or scholar track) | $50 |
| Candidate (analyst or scholar track) | $100 |
| Analyst, Scholar | $150 |

Members (no in-training or analyst role) and external visitors don't
owe dues.

### Sections on the Dues tab

- **Current academic year summary** — tier amounts inline, due date,
  obligated / paid / unpaid counts, total collected.
- **Totals collected per period chart** — bar chart, all years.
- **Per-role chart** — paid vs unpaid stacked bars for the current year.
- **Per-role table** — same data in tabular form.
- **Unpaid members** — list of members who owe dues for the current
  year and haven't paid. Each row shows the amount owed and a
  **Record payment** button. Email reminders go out every N days
  (configurable on Settings) starting after the due date.
- **All periods table** — every academic year you've configured, with
  tier amounts + paid / unpaid counts + collected.

### Common dues workflows

- **"A member just wrote me a check for dues."**
  → Dues tab → find them in Unpaid → click **Record payment**.
- **"A member paid via Stripe but it's not showing as paid."**
  → Payments tab → find their pending payment → **Mark paid**. (Should
  be rare; webhook usually handles this.)

---

## Members tab

Type a name or email in the search box, hit Search. Click **View** on
any result. The detail page shows:

- **Tuition enrollments** — every academic year, with status badge
  and (if on a payment plan) the installment schedule.
- **Payments** — chronological list of all payments by this member
  (dues, tuition, registrations, donations), with status badges.
- **Event registrations** — every event they've registered for, with
  status.

Use this as your one-stop lookup when someone asks "What's the story
with [member]?". The detail page is read-only — to make changes, go
to the relevant tab.

---

## Payments tab

The Payments tab is for inspecting or correcting individual payments.

- **Filters**: payment type (registration / dues / donation / tuition)
  and status (succeeded / pending / refunded / failed).
- **Each row** shows date, user, type (+ event for registrations),
  amount, method (Stripe / Offline), status badge, and actions:
    - **Mark paid** appears on pending offline payments. Runs the
      standard success side-effects: marks succeeded, issues a Receipt,
      sends emails.
    - **Refund** appears on succeeded Stripe payments. Issues a refund
      via the Stripe API and marks the payment refunded. **This is
      irreversible** — the confirmation prompt will warn you.

Offline payments don't show **Refund** because they're not in Stripe —
you have to handle reimbursement separately (cash, check, etc.) and
mark the payment refunded via Django admin (one of the few times
you'd visit Django admin).

---

## Settings tab

Per-academic-year amounts. Two tables:

- **Dues** — for each year, the three tier amounts (pre-cand /
  candidate / analyst).
- **Tuition** — for each year, the annual amount.

The current year is marked with a green dot. Editing past years
doesn't retroactively change anyone's recorded payments — it only
affects new payments and reminders.

Below the tables, the **Reminder cadences** section lets you change
how often the website emails reminders to unpaid members and undecided
students (in days). Defaults to 7 (weekly). Applies to the current
academic year; future years inherit on rollover.

> A new academic year is set up automatically each September. It
> inherits its amounts and reminder cadence from the previous year,
> so any changes you save above carry forward.

---

## Exports tab

Currently offers one download:

- **All transactions CSV** — every payment with user, amount, status,
  method, date, and Stripe reference. Suitable for bookkeeping or
  sharing with the board.

Event-specific roster CSVs live on each event's edit page
(`/events/<slug>/edit/` for staff and event-editors).

---

## What's NOT in the treasurer admin (and why)

You may occasionally need Django admin (`/admin/`) for:

- Editing a Receipt
- Marking an offline payment as REFUNDED (after handling reimbursement
  out-of-band)
- Bulk operations across many records

Everything else — recording payments, resolving tuition statuses,
issuing Stripe refunds, viewing member history, editing AY amounts,
adjusting reminder cadence — should be doable from the treasurer admin.
If you find yourself going to Django admin for something else, mention
it and we can probably bring it in.

---

## Things you don't have to do (the system handles them)

- **Issuing receipts** — happens automatically when a Stripe payment
  succeeds (or when you click **Record payment** / **Mark paid**).
- **Sending payment-success emails** — same.
- **Creating next year's academic period** — a cron sets up next year
  in advance so you can plan ahead in Settings.
- **Sending reminders** — a cron sends them on the cadence you set in
  Settings.

---

## What to ask Rico for help with

- Anything you'd want to do that isn't here.
- Anything that looks broken (a number doesn't add up, an email
  bounced, etc.).
- Setting up a new treasurer account (when you transition out).
