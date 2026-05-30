# Treasurer Admin Guide

*A walk-through of the treasurer admin: managing dues, tuition,
payments, refunds, and the academic-year settings that drive them.*

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

## Tuition

### Who pays tuition

The four "in-training" roles owe annual tuition:

- Pre-Candidate Analyst
- Candidate Analyst
- Pre-Candidate Scholar
- Candidate Scholar

Full Analysts, Scholars, Members, and external visitors do not pay
tuition.

**Total years required:** four. The years do **not** have to be
contiguous — a student may skip one or more years and pay them later.
A student transitions out of the in-training roles only after four total
tuition-paid years have been recorded. **Permanent exemption is not an
option** — skipping a year is fine but the four-year obligation stands.

### The annual decision

Each academic year (Sep 1 – Aug 31), every in-training student must
record one of these decisions for that year:

| Decision | Meaning |
|---|---|
| **Committed** | "I plan to pay this year" — but no payment received yet |
| **Payment plan** | "I want to pay in installments" — plan is set up |
| **Paid in full** | The annual tuition has been received |
| **Skipping** | "I'm not paying tuition this year" (pays regular event fees; year doesn't count toward the four) |

Students select `committed`, `payment_plan`, or `skipping` themselves
via `/tuition/`. `paid_in_full` is reached automatically when a payment
lands (Stripe Checkout or the treasurer recording an offline payment).

**Decision deadline:** August 31 by default (the day before the academic
year starts). Adjustable per academic year on the Settings tab.

**Reminders** go out automatically every N days from the decision-due
date onward, to students who haven't recorded a decision or whose
`committed` status hasn't been backed by a payment yet. Adjust the
cadence on the Settings tab.

### Sections on the Tuition tab

- **Current period summary** — top-of-page cards: in-training count,
  collected total, **reconciliation queue size**.
- **Status breakdown** — small-card grid showing how many students are
  in each status, including "Undecided" (no enrollment row recorded).
- **By role** — per-role table: total in role, how many decided, how
  many undecided, how many committed-but-unpaid.
- **Reconciliation queue** — the rows you should look at. These are
  either **undecided** or **committed without payment**. Each row has
  two action buttons:
    - **Record payment** — records an offline tuition payment for the
      annual amount, marks the enrollment Paid in Full, and sends the
      student a receipt + confirmation email. Use this when you've
      received their cash / check.
    - **Skipping** — sets the student's status to Skipping (their
      explicit "I'm not paying this year"). They'll still pay regular
      fees for any events; the year won't count toward their four.

> All actions are recorded in the enrollment's notes field with the
> date and your email, so there's an audit trail.

### Common tuition workflows

- **"A candidate just paid me the tuition amount in cash for this year."**
  → Tuition tab → find them in the reconciliation queue → click
  **Record payment**. Done. They get an email receipt.
- **"A candidate told me they want to do a payment plan."**
  → Tell them to go to `/tuition/` themselves and pick "I want to set
  up a payment plan", then choose 2 or 9 installments. They can pay
  each installment via Stripe.
- **"A candidate is skipping this year."**
  → Tuition tab → find them → click **Skipping**.

### How tuition status interacts with event registration

There are **two gates** in front of event registration for in-training
students. Both must clear for registration to go through.

#### Gate 1 — Broad: must have a decision recorded

If an in-training student has no `TuitionEnrollment` row for the current
period, they cannot register for *any* event type. They see a polite
403 page directing them to `/tuition/` to choose an option. Any of the
four decisions clears this gate — **including `skipping`**. The point
of this gate is to force engagement with the annual decision, not to
collect money.

#### Gate 2 — Narrow: committed-without-payment blocked from tuition-covered special events

This gate only fires when **all three** of the following are true:

1. The event's type is `special_event` (Days of Assembly, Working
   Days, Scholarly Seminars, and all annual-program types like
   seminars / reading groups / cartels do not engage this gate).
2. The student's status is `committed` — i.e. they said they'd pay
   this year, but no payment has been received and no payment plan is
   set up.
3. The event has a "covered by tuition" price tier matching the
   student's audience. (Whether a given event is tuition-covered is
   decided per-event by the staff who set up the event's price tiers.)

The intuition: this gate stops a student from claiming the "covered by
tuition" pricing path on a special event without having actually paid
for the tuition that would cover it. If the event isn't tuition-covered
in the first place, the student would just pay the regular fee and this
gate doesn't fire.

#### Full case table

The table reads as: *"a student with this tuition status, trying to
register for this kind of event, gets this outcome."* Gates apply in
order: Gate 1 first, then Gate 2.

| Tuition status | Annual-program event (seminar, RG, cartel) | Days of Assembly, Working Day, Scholarly Seminar | Special event (no covered tier) | Special event (with covered tier matching audience) |
|---|---|---|---|---|
| **No decision recorded** | Blocked by Gate 1 | Blocked by Gate 1 | Blocked by Gate 1 | Blocked by Gate 1 |
| **`committed`** | Allowed — pays regular fee or covered fare if covered tier exists | Allowed — same | Allowed — pays regular fee | **Blocked by Gate 2** — would be claiming uncompensated coverage |
| **`payment_plan`** | Allowed — tuition coverage applies if covered tier exists | Allowed — same | Allowed — pays regular fee | Allowed — covered (plan is set up) |
| **`paid_in_full`** | Allowed — tuition coverage applies if covered tier exists | Allowed — same | Allowed — pays regular fee | Allowed — covered |
| **`skipping`** | Allowed — pays regular fee (no tuition coverage available) | Allowed — same | Allowed — pays regular fee | Allowed — pays regular fee (covered tier does not apply to skipping students) |

**Non-in-training roles** (Analyst, Scholar, Member, external) are
never blocked by either gate. They register for events on the regular
rules: free where allowed, paid where required.

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
- **Totals collected per academic year chart** — bar chart, all years.
- **Per-role chart** — paid vs unpaid stacked bars for the current year.
- **Per-role table** — same data in tabular form.
- **Unpaid members** — list of members who owe dues for the current
  year and haven't paid. Each row shows the amount owed and a
  **Record payment** button. Email reminders go out every N days
  (configurable on Settings) starting after the due date.
- **All academic years table** — every year you've configured, with
  tier amounts + paid / unpaid counts + collected.

### Common dues workflows

- **"A member just wrote me a check for dues."**
  → Dues tab → find them in Unpaid → click **Record payment**.
- **"A member paid via Stripe but it's not showing as paid."**
  → Payments tab → find their pending payment → **Mark paid**. (Should
  be rare; the website usually handles this automatically.)

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
    - **Refund** appears on succeeded payments. For Stripe payments it
      issues an automatic refund via Stripe and marks the payment
      refunded (**irreversible** — the confirmation prompt will warn
      you). For offline payments it marks the payment refunded **for
      accounting purposes only** — no money moves through the system,
      so you'll need to send the refund check (or process the cash
      refund) manually. An audit note is added to the payment with the
      date and your email.
    - **Resend receipt** appears on succeeded payments that already
      have a receipt. Common when a member loses the original email or
      asks for a copy.

---

## Settings tab

Per-academic-year settings. Two tables:

- **Dues** — for each year, the three tier amounts (pre-cand /
  candidate / analyst).
- **Tuition** — for each year, the annual amount and the
  **decision due date** (defaults to August 31, the day before the AY
  starts).

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

## Things you don't have to do (the system handles them)

- **Issuing receipts** — happens automatically when a Stripe payment
  succeeds (or when you click **Record payment** / **Mark paid**).
- **Sending payment-success emails** — same.
- **Creating next year's academic period** — set up automatically so
  you can plan ahead in Settings.
- **Sending reminders** — sent on the cadence you set in Settings.

---

## When to ask the Web Coordinator for help

- Bulk operations across many records.
- Anything that looks broken (a number doesn't add up, an email
  bounced, etc.).
- Setting up a new treasurer account (when you transition out).
- Anything you'd like to do that this admin doesn't yet handle.
