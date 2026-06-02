# Treasurer Admin Guide

*A walk-through of the treasurer admin: managing dues, tuition,
payments, refunds, and the academic-year settings that drive them.*

---

## How to get there

1. Log in at <https://app.lacanschool.org/> with your treasurer account.
2. Click your photo / initials in the top-right.
3. Choose **Staff tools** from the dropdown.
4. On the Staff tools page, click the **Treasurer** card.

That's the path for a treasurer account. (If your account also has full
site-admin rights, you'll additionally see a direct **Treasurer dashboard**
link right in the dropdown — either route lands in the same place.)

You'll arrive on the **Overview** tab. Eight tabs run across the top:

| Tab | What it's for |
|---|---|
| **Overview** | At-a-glance snapshot of tuition + dues for the current academic year |
| **Tuition** | Per-student tuition status, any year, plus all-years trends |
| **Dues** | Per-member dues status, any year, plus all-years trends |
| **Members** | Look up any member to see their full payment history |
| **Payments** | Chronological list of all payments with refund / mark-paid controls |
| **Settings** | Edit dues + tuition amounts and reminder cadence per academic year |
| **Exports** | Download CSVs of payment data |
| **Help** | This page |

---

## Overview tab

Two cards summarizing the current academic year — **Tuition on the left,
Dues on the right** — each leading with the dollar figures that matter and a
small bar showing the split:

- **Tuition card**: the annual amount, then three featured totals —
  **Collected** (money in), **Planned, unpaid** (remaining balances from
  students who committed or are on a payment plan), and **Owed, undecided**
  (students who owe a decision but haven't recorded one). Below: in-training
  count, the **reconciliation queue size**, and total outstanding.
- **Dues card**: the three tier amounts and due date, then **Collected** vs
  **Outstanding** (what unpaid obligated members still owe), with
  obligated / paid / unpaid counts.

Use this to see at a glance whether anything needs work. If the tuition
reconciliation queue is non-zero, open the Tuition tab.

---

## Reading the historical data

Before you dig in, some context on what's already loaded:

- **AY 2024–25 and 2025–26 were imported** from the previous treasurer's
  spreadsheets — tuition and dues payments, with the matching students/members.
- For tuition, **a student who has no payment recorded for a year is shown as
  "Skipping" that year.** For past years this is an *assumption* (we didn't have
  per-year enrollment records), so don't read it as a confirmed choice.
- Each record quietly carries a **provenance** — imported, verified (a real
  Stripe payment), assumed, or staff-entered — so that when we later confirm
  figures against bank/Stripe records, confirmed data is promoted rather than
  overwritten.
- A short **member survey at launch** will let people confirm their own join
  year and which years they paid, which will firm up the older numbers.

So: current-year figures are solid; the further back you look, the more the
"Skipping" rows are best-guesses awaiting confirmation.

---

## Tuition tab

At the top is a **year selector** — the dashboard opens on the current academic
year, but you can switch to any past year to see exactly who paid and what was
collected. The current year additionally shows the forward-looking tools
(reconciliation queue, record-payment buttons); past years show the
retrospective record only.

### Who pays tuition

The four "in-training" roles owe annual tuition:

- Pre-Candidate Analyst
- Candidate Analyst
- Pre-Candidate Scholar
- Candidate Scholar

Full Analysts, Scholars, and external visitors (Auditors) do not pay tuition.

**Total years required:** four. The years do **not** have to be
contiguous — a student may skip one or more years and pay them later.
A student transitions out of the in-training roles only after four total
tuition-paid years have been recorded. **Permanent exemption is not an
option** — skipping a year is fine, but the four-year obligation stands.

### The annual decision

Each academic year (Sep 1 – Aug 31), every in-training student records one
of these for that year:

| Decision | Meaning |
|---|---|
| **Committed** | "I plan to pay this year" — but no payment received yet |
| **Payment plan** | "I want to pay in installments" — plan is set up |
| **Paid in full** | The annual tuition has been received |
| **Skipping** | "I'm not paying tuition this year" (pays regular event fees; the year doesn't count toward the four) |

Students choose `committed`, `payment_plan`, or `skipping` themselves at
**`/tuition/`**. `paid_in_full` is reached automatically when payment lands
(Stripe Checkout, or you recording an offline payment).

**Decision deadline:** August 31 by default (the day before the academic year
starts). Adjustable per year on the Settings tab. **Reminders** go out
automatically every N days from that date to students who haven't decided or
whose `committed` status isn't yet backed by a payment.

### Sections on the Tuition tab

- **Selected-year summary** — the dollar tiles (Collected / Planned-unpaid /
  Owed-undecided) and bar, plus in-training count, outstanding, and the
  reconciliation queue size.
- **Status breakdown** — how many students are in each status
  (paid-in-full / payment-plan / committed / skipping, and — current year only
  — "Undecided" = no decision on file).
- **By role** *(current year)* — per-role table: total, decided, undecided,
  committed-but-unpaid.
- **Reconciliation queue** *(current year)* — the rows that need you: students
  who are **undecided** or **committed without payment**. Each has two buttons:
    - **Record payment** — records an offline tuition payment for the annual
      amount, marks the enrollment Paid in Full, and emails the student a
      receipt. Use this when you've received their cash / check.
    - **Skipping** — sets their status to Skipping.
- **Students this year** — the full roster of recorded students for the
  selected year, each with status, amount paid, and remaining balance.
- **All academic years** *(bottom)* — the longitudinal view: a table of every
  year (enrolled, status counts, collected) plus two charts —
  **tuition collected per year** and **students by status per year**. Click any
  year in the table to jump to it.

> Actions are recorded in the enrollment's notes with the date and your email,
> so there's an audit trail.

### Common tuition workflows

- **"A candidate paid me the tuition amount in cash for this year."**
  → Tuition tab → find them in the reconciliation queue → **Record payment**.
- **"A candidate wants to do a payment plan."**
  → Have them go to `/tuition/` and pick "set up a payment plan" (2 or 9
  installments), payable via Stripe.
- **"A candidate is skipping this year."**
  → Tuition tab → find them → **Skipping**.
- **"What did 2024–25 look like?"**
  → Tuition tab → year selector → pick AY 2024–25.

### How tuition status interacts with event registration

There are **two gates** in front of event registration for in-training
students. Both must clear for registration to go through.

#### Gate 1 — Broad: a decision must be on file

An in-training student with no tuition decision recorded for the current year
cannot register for *any* event. They see a polite page directing them to
`/tuition/`. **Any** of the four decisions clears this gate — **including
`skipping`**. The point is to force engagement with the annual decision, not to
collect money.

#### Gate 2 — Narrow: committed-without-payment blocked from a tuition-covered special event

This gate fires only when **all three** are true:

1. The event's type is **Special event** (Days of Assembly, Working Days,
   Scholarly Seminars, and the annual-program types — seminars, reading groups,
   cartels — do **not** engage this gate).
2. The student's status is **`committed`** — they said they'd pay, but no
   payment and no payment plan is on file.
3. The event has a "covered by tuition" price tier matching the student's
   audience (whether an event is tuition-covered is set per-event by whoever
   configures its price tiers).

The intuition: this stops a student from claiming "covered by tuition" pricing
on a special event without having paid the tuition that would cover it. If the
event isn't tuition-covered, the student just pays the regular fee and this gate
never fires.

#### Full case table

Read as: *"a student with this tuition status, registering for this kind of
event, gets this outcome."* Gate 1 applies first, then Gate 2.

| Tuition status | Annual-program event (seminar, RG, cartel) | Day of Assembly, Working Day, Scholarly Seminar | Special event (no covered tier) | Special event (covered tier matching audience) |
|---|---|---|---|---|
| **No decision recorded** | Blocked by Gate 1 | Blocked by Gate 1 | Blocked by Gate 1 | Blocked by Gate 1 |
| **`committed`** | Allowed — regular or covered fare if a covered tier exists | Allowed — same | Allowed — pays regular fee | **Blocked by Gate 2** — would claim coverage not paid for |
| **`payment_plan`** | Allowed — coverage applies if a covered tier exists | Allowed — same | Allowed — pays regular fee | Allowed — covered (plan is set up) |
| **`paid_in_full`** | Allowed — coverage applies if a covered tier exists | Allowed — same | Allowed — pays regular fee | Allowed — covered |
| **`skipping`** | Allowed — pays regular fee (no coverage) | Allowed — same | Allowed — pays regular fee | Allowed — pays regular fee (coverage doesn't apply to skipping) |

**Non-in-training roles** (Analyst, Scholar, Auditor) are never blocked by
either gate — they register on the regular rules: free where allowed, paid
where required.

---

## Dues tab

Dues are **per-academic-year** and **tiered by role**:

| Role | Default annual dues |
|---|---|
| Pre-candidate (analyst or scholar track) | $50 |
| Candidate (analyst or scholar track) | $100 |
| Analyst, Scholar | $150 |

External visitors (Auditors) don't owe dues.

Like Tuition, the Dues tab has a **year selector** at the top. The current year
shows the live picture (who still owes, with record-payment buttons); past years
show who paid and how much was collected.

### Sections on the Dues tab

- **Selected-year summary** — *current year:* obligated / paid / unpaid counts,
  Collected vs Outstanding, and a small split bar. *Past years:* paid count and
  collected total.
- **Paid / unpaid by role** *(current year)* — a stacked bar plus a per-role
  table.
- **Unpaid members** *(current year)* — everyone who still owes for the year,
  each with the amount owed and a **Record payment** button. Reminders email
  out every N days (set on Settings) after the due date.
- **Payments received** — for the selected year, who paid: name, role, amount,
  date, and method. This is accurate for any year, even as the roster changes
  over time.
- **All academic years** *(bottom)* — a table of every year (tiers, paid count,
  collected; unpaid only shown for the current year, where it's meaningful)
  plus two charts: **dues collected per year** and **paying members per year**.
  Click a year to jump to it.

### Common dues workflows

- **"A member wrote me a check for dues."**
  → Dues tab → find them in Unpaid → **Record payment**.
- **"A member paid via Stripe but it's not showing as paid."**
  → Payments tab → find their pending payment → **Mark paid**. (Rare — the
  website normally handles this automatically.)

---

## Members tab

Type a name or email, hit **Search**, and click **View** on a result. The detail
page shows:

- **Tuition enrollments** — every year, with status badge and (on a payment
  plan) the installment schedule.
- **Payments** — every payment by this member (dues, tuition, registrations,
  donations), most recent first, with status badges.
- **Event registrations** — every event they've registered for, with status.

Use this as your one-stop lookup for "What's the story with [member]?" The page
is read-only — to make a change, go to the relevant tab.

---

## Payments tab

For inspecting or correcting individual payments.

- **Filters**: payment type (registration / dues / donation / tuition) and
  status (succeeded / pending / refunded / failed).
- **Each row** shows date, member, type (+ event for registrations), amount,
  method (Stripe / Offline), status, and actions:
    - **Mark paid** — on pending offline payments. Runs the standard success
      side-effects: marks succeeded, issues a receipt, sends emails.
    - **Refund** — on succeeded payments. For **Stripe** payments it issues an
      automatic refund and marks it refunded (**irreversible** — the prompt
      warns you). For **offline** payments it marks it refunded **for accounting
      only** — no money moves, so you send the actual check / cash refund
      yourself. An audit note records the date and your email.
    - **Resend receipt** — on succeeded payments that have a receipt; handy when
      a member loses the original.

---

## Settings tab

Per-academic-year settings, in two tables:

- **Dues** — for each year, the three tier amounts (pre-cand / candidate /
  analyst).
- **Tuition** — for each year, the annual amount and the **decision due date**
  (defaults to August 31, the day before the year starts).

The current year is marked. Editing a past year does **not** retroactively
change anyone's recorded payments — it only affects new payments and reminders.

Below the tables, **Reminder cadences** sets how often the website emails
reminders to unpaid members and undecided students (in days; default 7).
Applies to the current year; future years inherit it on rollover.

> A new academic year is set up automatically each September, inheriting its
> amounts and cadence from the previous year — so changes you save here carry
> forward.

---

## Exports tab

- **All transactions CSV** — every payment with member, amount, status, method,
  date, and Stripe reference. Good for bookkeeping or sharing with the board.

Per-event registration rosters aren't here — they live on each event's page
(open an event under **Events** or **Program** and use its "Roster CSV" link).

---

## Things you don't have to do (the system handles them)

- **Issuing receipts** — automatic when a Stripe payment succeeds (or when you
  click **Record payment** / **Mark paid**).
- **Sending payment-success emails** — same.
- **Creating next year's academic period** — set up automatically so you can
  plan ahead in Settings.
- **Sending reminders** — sent on the cadence you set in Settings.

---

## When to ask the Web Coordinator for help

- Bulk operations across many records (e.g. correcting a whole year's data once
  bank records arrive).
- Anything that looks broken (a number doesn't add up, an email bounced).
- Setting up a new treasurer account (when you transition out).
- Anything you'd like to do that this admin doesn't yet handle.
