# Treasurer Admin Guide

*A walk-through of the treasurer admin: the unified member ledger, dues,
tuition, payments, refunds, and the academic-year settings that drive them.*

---

## How to get there

1. Log in at <https://app.lacanschool.org/> with your treasurer account.
2. Click your photo / initials in the top-right.
3. Choose **Staff tools** from the dropdown.
4. On the Staff tools page, click the **Treasurer** card.

That's the path for a treasurer account. (If your account also has full
site-admin rights, you'll additionally see a direct **Treasurer dashboard**
link right in the dropdown — either route lands in the same place.)

You'll arrive on the **Overview** tab. Seven tabs run across the top:

| Tab | What it's for |
|---|---|
| **Overview** | Academic-year tiles plus one needs-attention queue — everything that wants you, in one place |
| **Accounts** | Every member's balance on the unified ledger — search, filter, and sort, with the URL carrying your filters so a filtered view is a shareable link |
| **Payments** | Chronological list of all payments with refund / mark-paid controls |
| **Reconcile** | Member-submitted history reports awaiting a decision, provisional payments awaiting categorization, Stripe payments with no linked member, and charge conflicts |
| **Settings** | Edit dues + tuition amounts and reminder cadence per academic year |
| **Exports** | Download CSVs of transactions and member balances |
| **Help** | This page |

---

## How the account works

There is **one account per member** — not a separate tuition ledger, a
separate dues ledger, and so on. That used to be the design, and it
caused real confusion: the school's historical records simply aren't
clean enough to say with confidence which dollar paid which year's
tuition versus which year's dues. So the ledger now works the
traditional way — one account per member, with two kinds of entries:

- **Charges** — what a member owes. A charge is created for each year's
  dues, for each year of tuition a student owes (up to the four-year
  requirement, and only for years they haven't marked Skipping), and for
  each event registration fee once it settles.
- **Payments** — money that came in, whether through Stripe or recorded by
  you as an offline cash/check/arrangement.

All of a member's charges and payments sit together on **one running
balance**, so a member who overpaid one thing and underpaid another shows
their *true net position* — one number — rather than a confusing mix of
"behind on dues, ahead on tuition" that never quite made sense.

Whether an **individual charge** reads paid is a narrower question, and
it's answered per category. Tuition coverage counts tuition payments only;
dues coverage counts dues payments only; registration the same. Within a
category the oldest charge is covered first. Money paid under one heading
never settles a charge under another.

The two ideas work together: the balance tells you what the member owes
the school all told, and the per-category coverage tells you what that
money was for. A member can be square overall and still show an unpaid
dues year, which means the money came in under a different heading, and
the fix is to **re-categorize the payment**, not to read the dues as paid.

This matters most for the per-year tuition table and the four-year
requirement, which are read off tuition coverage. Money that was never
tuition can no longer make a tuition year look part-paid.

Two tuition figures the school tracks closely follow from that:

- **Total tuition paid** — the running sum of tuition payments, shown on
  every member's account page.
- **Tuition-years progress** — in-training members (Pre-Candidate and
  Candidate, on either the analyst or scholar track) owe **four years** of
  tuition total. The years don't have to be contiguous — a student may mark
  a year **Skipping** and pay it later — but the requirement is capped at
  four; it's never open-ended, and it's never waived permanently. Skipping
  a year means that year doesn't generate a tuition charge; when a
  non-skipping year is fully covered by the sweep, it counts toward the
  four.

That four-year number drives **two different things**, and they're easy to
conflate:

- **"Requirement met"** — the green badge on the tuition tile, and the
  per-year "requirement met" state on the Tuition decisions table — means
  the member has **paid in full across all four years**. It's payment-based.
- The **annual-decision exemption** is a separate, quieter milestone: once a
  member has **four non-skipping years on record** (committed, on a payment
  plan, or paid — Skipping doesn't count), they stop being asked for a
  yearly decision — no more Undecided-queue nag, no more registration block —
  whether or not every one of those years is actually paid off. A member can
  be decision-exempt and still owe real money; that money is chased through
  the balance on their statement, not through decision reminders. Don't read
  "no decision needed" as "nothing owed" — the balance tile is the source of
  truth for that.

Full Analysts, Scholars, and external visitors (Auditors) never owe
tuition. Becoming an Analyst or Scholar certifies the four-year
requirement was completed, so a transitioned member's tuition history is
frozen: the website stops minting, changing, or flagging their tuition
charges, and any old tuition charge on their account exists only where a
recorded payment covers it. Dues, by contrast, are owed annually by every
in-training and full member (not Auditors), tiered by role — the amounts
live on the Settings tab.

Because that four-year certification means something, the website won't
let a student be **promoted to Analyst or Scholar while tuition is
unsettled** — any tuition charge with money still owed on it, or fewer
than four years covered, blocks the promotion. This gate applies wherever
a role change like that can happen: the Meeting of Analysts' advancement
approval, the Board's membership-change form, a role edit in the Django
admin, and the CSV member importer (which skips the row and warns rather
than failing the whole file). A promotion that's blocked this way shows
you exactly why — which years and how much — right on the advancement
page. **There's no override switch.** The fix is always on the member's
account page: record the missing payment, adjust a charge, waive it, or
void it — whatever's true — and the promotion clears on retry. A waived
year settles the money owed but does **not** count as one of the four
covered years; if the school means to credit a year without collecting
payment for it, that's a decision for the tuition-years count itself, not
something a waiver does as a side effect.

### Dues, all years

Dues is tracked as its own running bucket, the way tuition is: total dues
charged against total dues paid, with a **dues balance**. You'll see it on
the member's account page (a "Dues, all years" tile plus a **Dues by
year** table), as a column on the Accounts roster, and in the balances
CSV. The older "Dues this AY" badge is still there for the current year's
status. Members see the same all-years summary on their own account tab.

---

## Overview tab

Tiles across the top summarize the current academic year:

- **Collected this AY** — total money in, broken out underneath by dues /
  tuition / registration / donation.
- **Outstanding** — the total everyone still owes (click through to
  Accounts, pre-filtered to owing).
- **Accounts owing** and **Accounts in credit** — headcounts, each a link
  into the filtered Accounts view.

Below the tiles is the **needs-attention queue** — the one place that
surfaces everything that wants a decision from you:

- **Undecided** — in-training members with no tuition decision on file for
  the current year. Each row has a one-click **Skipping** button if that's
  the right call; otherwise open their account page to record what they
  told you. A member drops off this list once they're decision-exempt (four
  non-skipping years on record) even if they still owe money — see *How the
  account works*, above.
- **Committed, not yet paid** — members who said they'd pay tuition this
  year but no payment (or payment plan) is on file yet. Click through to
  their account page to record it once it arrives.
- **Charge conflicts** — a staff-adjusted charge that disagrees with what
  the system would otherwise expect (see *Reconcile tab*, below).
- **Assumed**, **No payer**, and **Member submissions** counts — link
  straight to the Reconcile tab (see *Reconcile tab*, below, for what each
  one is).

If the queue is empty, there's nothing waiting on you today.

---

## Accounts tab

The full member roster, one row per account: obligation, paid, balance,
tuition-years progress (n of 4), dues across all years, and the date of
the last payment. A **Sync charges** button mints any missing
current-year dues charges — use it if a new member joined mid-year or a
role change wasn't picked up automatically.

**Sync charges is about what members owe, not what they've paid.** It
mints obligations from the dues tier table; it never contacts Stripe and
never pulls in payments. Payments arrive on their own (see *What happens
automatically* below), so there is nothing to press to fetch them.

Filters sit above the table and **live in the page's URL**:

- **q** — search by name or email.
- **balance** — Any / Owing / Credit / Square.
- **role** — any LSP role.
- **sort** — most owed first (default), name, most paid, or latest payment.

Because the filters are query-string parameters, a filtered view — say,
"everyone who's owing" — is a link you can copy and send, or bookmark, and
it will reopen exactly that view.

---

## Reading a member's statement

Click any member on the Accounts tab (or search from there) to open their
account page. It has four parts:

1. **Tiles** — balance (owed, in credit, or "Paid up"), total tuition
   paid, tuition years covered out of four, and a dues-this-AY badge.
   If a payment pushed the balance into credit while a tuition year is
   marked Skipping, a warning banner explains the likely mix-up — a
   skipped year that was actually paid — so you can fix the decision at
   its source.
2. **Tuition decisions** — one row per academic year the member has an
   enrollment for: their decision, the year's rate, and where that
   charge stands (paid / partial / unpaid / waived / requirement met /
   skipping). The current year's row gets **Committed** and **Skipping**
   buttons so you can set it directly here, without sending the member
   back to `/tuition/`.
3. **Statement** — the heart of the page: every charge and payment,
   chronological, with a **running balance** column so you can see the
   account's history unfold. Each charge row carries **Waive**, **Void**,
   and **Adjust** actions (and **Reopen** once waived); each payment row
   carries **Mark paid** (pending offline payments), **Refund**,
   **Resend receipt**, and **Re-categorize** as applicable (see *Payments
   tab*, below, for what Re-categorize does). Hovering a line's provenance icon
   shows where it came from — imported, verified, assumed, member-reported,
   or staff-entered — and any notes attached. The member sees their own
   simplified version of this same statement on their Account tab, with
   **Re-categorize**, **Split**, and **Note** actions on their own rows (see
   the note under *Payments tab*, below) — so a line here can already carry
   a member-reported provenance and audit note by the time you look at it.
4. **Actions** — an **Add a charge** form (any category, amount, effective
   date, and an optional note) and a **Record an offline payment** form
   that takes any category and amount. Recording an offline **tuition**
   payment keeps the old side-effects — it sets the year's enrollment to
   Committed if needed and creates the matching installment record — so
   nothing downstream breaks.

Every one of these actions writes a **dated, attributed note** onto the
charge or payment it touched (who did it, when, and what changed), so the
statement doubles as an audit trail. Below the statement, the member's
event registrations are listed for reference.

---

## Historical data

Some context on what's already loaded, and what still needs your eye:

- **AY 2024–25 and 2025–26 were imported** from the previous treasurer's
  spreadsheets — tuition and dues payments, matched to the students and
  members on file.
- Every charge and payment carries a **provenance**: imported, verified (a
  real Stripe payment), assumed, or staff-entered — visible on hover on
  the statement — so that when a figure is later confirmed against
  bank/Stripe records, the confirmed version can be trusted over a guess.
- **Dues charges were backfilled** for past academic years back to the
  first well-recorded year, and those backfilled charges are marked
  **assumed** — a best guess that a member owed dues that year, not a
  confirmed fact. **Before the reminder emails are switched back on at
  launch**, review the Accounts tab filtered to **Owing**, and for each
  assumed charge you don't believe is real, **waive it** from that
  member's statement. This pass matters: an unreviewed assumed charge
  will otherwise nag a member who actually paid, or who joined after that
  year, with a reminder email they shouldn't get.

So: current-year figures are solid; the further back you look, the more a
row is a best guess awaiting your review.

---

## Common workflows

- **"A member paid me dues or tuition in cash or by check."** → open their
  account page → **Record an offline payment** → pick the category and
  enter the amount. A receipt and confirmation email go out automatically,
  same as a Stripe payment.
- **"A student is skipping tuition this year."** → open their account page
  → **Tuition decisions** table → **Skipping** on the current year's row
  (or use the one-click **Skipping** button from the Overview queue if
  they're listed there as undecided).
- **"I want to forgive a charge."** → open the member's account page →
  find the charge on the statement → **Waive**. Waived charges stay
  visible (for the record) but drop out of the obligation total; **Reopen**
  undoes it if you change your mind.
- **"Why does this member show as owing?"** → open their account page and
  read the statement top to bottom: it's their obligation (every open
  charge) minus what's come in, across every category. A member can look
  "behind" on one category while actually ahead overall — the running
  balance at the bottom of the statement is the real answer, and the
  per-category coverage tells you which heading the money came in under.

Members can't accidentally pay dues twice — the `/dues/` page checks
whether a real payment already exists for the current period before
letting them start a new Stripe checkout, independent of whether a charge
has been minted yet.

---

## Tuition & registration gate

There is **one gate** in front of event registration for in-training
students. (It keys off a student's **tuition decision** for the year — money
doesn't drive it, the decision does.)

### A decision must be on file

An in-training student with no tuition decision recorded for the event's
academic year cannot register for *any* event. They see a polite page
directing them to `/tuition/`. **Any** decision clears this gate —
**including `skipping`**, and including a payment plan still awaiting the
Board. The point is to force engagement with the annual decision, not to
collect money.

### Coverage is per event, and every non-skipping decision gets it

Whether an event is covered by tuition is set **per event**, by whoever
configures its price tiers (a tier with "covered by tuition" checked,
matching the student's audience). Where such a tier exists, it applies to
every non-skipping decision: `committed`, `plan_requested`, `payment_plan`,
and `paid_in_full` alike. Where it doesn't, the student pays the regular fee
whatever their tuition status.

Until task #484 (2026-07-29) a second gate blocked a `committed`
student from a tuition-covered **special event**, on the grounds that they
would be claiming coverage they hadn't paid for. That gate is gone: the fee
is waived on the assumption tuition will be paid, and a plan application
pending with the Board is treated the same way rather than waiting on the
Board's turnaround.

### Full case table

Read as: *"a student with this tuition status, registering for this kind
of event, gets this outcome."*

| Tuition status | Any event with no covered tier for their audience | Any event with a covered tier matching their audience |
|---|---|---|
| **No decision recorded** | Blocked | Blocked |
| **`committed`** | Allowed — pays regular fee | Allowed — covered |
| **`plan_requested`** (with the Board) | Allowed — pays regular fee | Allowed — covered |
| **`payment_plan`** | Allowed — pays regular fee | Allowed — covered |
| **`paid_in_full`** | Allowed — pays regular fee | Allowed — covered |
| **`skipping`** | Allowed — pays regular fee | Allowed — pays regular fee (coverage doesn't apply to skipping) |

### Skipping a year whose events tuition already covered

Coverage is provisional in one direction: a member can register for a covered
event and *later* record that they're skipping tuition for the year (or have a
payment-plan application declined and then choose to skip). When they record
skipping, the site shows them every event tuition covered that year with its
regular fee and a total, and on confirmation **re-bills each one**: the
registration moves to Awaiting payment at the regular fee, which turns on its
"Pay" button and the ordinary registration reminders. They lose event access
until it's settled.

The reverse also holds. If they later record that they plan to pay tuition, or
apply for a plan, those registrations go straight back to covered at $0 and
access returns, with no money moving. A fee they already **paid** is never
unwound automatically, that's a refund for you to decide on.

**This only fires on the member's own confirmed action.** Setting someone's
tuition status yourself, in the Django admin or from the Accounts tab, does not
re-bill anything, and neither do the import or backfill commands. If a member's
year should be re-billed and they haven't done it themselves, adjust the
registration amount, or add a charge on their account page.

**Non-in-training roles** (Analyst, Scholar, Auditor) are never blocked by
the gate — they register on the regular rules: free where allowed, paid
where required.

---

## Payments tab

For inspecting or correcting individual payments.

- **Filters**: payment type (registration / dues / donation / tuition) and
  status (succeeded / pending / refunded / failed / abandoned).
- **Each row** shows date, payer, type (+ event for registrations),
  amount, method (Stripe / Offline), status, and actions. The **Payer**
  column shows the member's name when the payment is linked to an
  account; when it isn't, it shows whatever Stripe told us about the
  payer — a name or an email — with an "unlinked" badge, so an unmatched
  payment is never just "anonymous". The actions are:
  - **Split** — divides one payment into parts with different categories,
    when a single check or charge covered several things at once (say,
    $400 that was really $150 dues plus a $250 seminar fee). The amounts
    must add up exactly; each Registration part can tick "insert matching
    charge" for the honor-system case described under Re-categorize. Rows
    from a split carry a **split** badge, and refunding **any** part
    refunds the **entire original charge** — the confirmation warns you,
    with the full original amount, before anything happens.
  - **Assign** — links (or re-links) the payment to a member's account.
    Start typing a name or email and pick from the list. The payment's
    money moves onto that member's running balance, its provenance is
    marked verified, and a dated audit note records who it was
    attributed to before. Registration payments can't be re-assigned
    here — the registration owns its member.
  - **Mark paid** — on pending offline payments. Runs the standard success
    side-effects: marks succeeded, issues a receipt, sends emails.
  - **Refund** — on succeeded payments. For **Stripe** payments it issues
    an automatic refund and marks it refunded (**irreversible** — the
    prompt warns you). For **offline** payments it marks it refunded **for
    accounting only** — no money moves, so you send the actual check /
    cash refund yourself. An audit note records the date and your email.
  - **Resend receipt** — on succeeded payments that have a receipt; handy
    when a member loses the original.
  - **Re-categorize** — fixes a payment that was logged under the wrong
    category (a check marked dues that was really tuition, that sort of
    thing). Pick the correct category, and if it's dues or tuition, which
    year it belongs to (the form guesses the year from the payment's date;
    override it if needed). When the correct category is **Registration**
    and the original event fee was never recorded — common for the
    honor-system years, where a $250 "tuition" payment was often really a
    seminar fee — tick **"Also insert a matching Registration charge"**:
    the charge is created with the payment's own date and amount, so the
    pair nets to zero on the member's statement instead of appearing as
    credit for a fee we have no record of. There's deliberately no
    automatic detection here: one $250 payment can be a partial tuition
    installment or a seminar fee, and repeated same-amount payments can be
    a payment plan or per-meeting billing — only you can tell which. The
    change writes a dated audit note to the payment. **Donations can be
    flipped** into or out of another category here — the members' own
    version of this action allows it too now (see the note below). Because
    donations sit outside the ledger's obligation math, flipping one
    **moves money in or out of the member's account pot**: turning a
    donation into tuition adds a charge-covering payment to their balance;
    turning a tuition payment into a donation removes one. If you re-categorize a
    payment **away from tuition** and it was backing an unpaid
    installment, the installment goes back to unpaid and a review note is
    added to that year's tuition decision — the decision itself doesn't
    change automatically (that's still yours to set). And if the payment
    belongs to a **transitioned member** (an Analyst or Scholar, tuition
    history frozen), re-categorizing it doesn't touch their frozen
    charges — follow up with a manual **Adjust** or **Void** on the
    relevant charge from their account page so the statement still adds
    up.

**"Pending" doesn't mean money is on the way.** A payment row is created
the moment a member is sent to Stripe's checkout page, before they type a
card number, so **Pending means only that we asked**. Most pending rows
you'll ever see are people who closed the tab. Stripe closes an unfinished
checkout after about a day, and the site then marks that row
**Abandoned** — no money was taken, nothing is owed to anyone, and the
member's registration stays open so they can still pay (the reminders keep
nudging them). Abandoned rows are kept rather than deleted so the record
of the attempt survives; filter them out with the status filter. If a row
sits at Pending for more than a day or two, that's worth mentioning to the
web coordinator — every Stripe payment is checked nightly, so a stale
Pending row shouldn't persist. Offline pending rows are different: those
are your own manual records, waiting for **Mark paid**.

This tab, and everything on it besides Re-categorize, is unchanged by the
ledger rework — it's still the place to inspect or correct one payment at
a time. The per-member **Statement** on the Accounts tab is the place to
see how that payment fits into the bigger picture (and offers the same
Re-categorize action per row, plus **Split**, described above).

**Members can now do some of this themselves.** From their own Account tab
statement, a member can re-categorize or split one of their **own**
payments — full parity with the actions above, including flipping a
donation. (Same restriction as yours: a payment that settles an event
registration can't be re-categorized or split, on either side.) That means
**a payment's category can change without any action from you** — a member
fixing their own mislabeled check is expected, not a bug. You can always
tell who did what: hover a statement line's provenance icon. A member-made
change shows a **"Member-reported (survey)"** source badge (a holdover
label — it also covers the newer self-service actions and the
history-submissions queue below, not just the original tuition survey),
and the note underneath spells out what happened and names the member's
email, e.g. "Re-categorized Dues → Tuition by member alice@example.com."
A treasurer's own edit instead shows a **"Verified against records"**
badge and a note naming you. Members also have their own **Note** field
per payment (`member_note`) — separate from your treasurer-only notes —
which shows in the same popover, labeled "Member note: …".

One case still needs your eyes: if the member is a **transitioned member**
(Analyst or Scholar, tuition history frozen) and re-types old money into or
out of tuition, that re-type doesn't touch their frozen charges — same as
when you do it yourself (above) — and the Reconcile tab's Charge conflicts
queue won't flag it, since nothing there disagrees with a sync that no
longer runs for them. Check their statement adds up and follow up with a
manual **Adjust** or **Void** if it doesn't.

---

## Reconcile tab

Everything that needs a human decision before it settles cleanly onto
someone's ledger. Four sections, in the order they appear:

- **Member submissions** — see below.
- **Charge conflicts** — a staff-adjusted charge that disagrees with what
  the minting sync would otherwise expect. The sync never edits a charge
  you've touched (`staff_adjusted`), so a disagreement lands here instead
  of silently being overwritten. Read the note, and adjust either side by
  hand.
- **Reconcile provisional payments** — payments imported as **assumed**
  (mostly recurring charges booked as tuition pending the member survey).
  Grouped by payer; confirm or reclassify each payer's group in one submit.
- **No payer** — Stripe charges that are categorized but linked to no
  member, so they never show up on anyone's statement. Link each to a
  member, or mark it an anonymous donation.

### Member submissions

Members can report a payment or fee from **before the website's records
begin** — the honor-system era a spreadsheet import can't reliably
reconstruct. From their Account tab, a member fills in what it was (a
payment or a charge), the category, amount, date, and a free-text
description ("Report missing history"), which files as a **pending**
submission. Nothing lands on their account yet — that's your call.

Each pending submission shows here with the member's name, what they
claimed, and their description. A submission may also carry a soft warning
— **possible duplicate claim** (another pending submission from the same
member looks identical: same kind, category, amount, and date — they may
have submitted twice by accident) or **no matching charge on file** (a
claimed *payment* in dues/tuition whose date falls in an AY with no charge
on record for it). Neither warning blocks approve/decline — they're just
worth a second look before you click.

You either:

- **Approve** — mints the matching entry on the member's account:
  a **payment** (offline, member-reported provenance, dated the day they
  claimed) for a claimed payment, or an **open charge** (also
  member-reported, and marked staff-adjusted so the minting sync leaves it
  alone) for a claimed fee. Either way it's bound to the matching academic
  year *only when the claimed date actually falls inside one* — a dues or
  tuition claim from before any period on file (the honor-system era) is
  minted **unbound** rather than mis-attributed to whichever year happens
  to be current right now, which would otherwise wrongly mark this year as
  already paid. The mint carries a note identifying the submission number
  and your email, plus the member's own description — so the provenance
  trail is complete. If a non-void charge already exists for that member in
  that category and year, approval is **refused** rather than
  double-minting — the message tells you to adjust the existing charge
  instead and decline the submission with a note pointing at it.

  Approving a **payment** claim credits the member's balance immediately,
  whether or not the fee it's paying off was ever recorded as a charge (see
  the "no matching charge on file" warning above). If the fee itself is
  also missing, approve the matching **charge** claim too (or add one
  yourself from their account page) so the payment actually covers
  something instead of just sitting as an unexplained credit.
- **Decline** — mints nothing. Whatever note you enter (a reason, a
  request for more detail, a reference to where you found the real record)
  is saved as the decision note. This note is shown to the member on their
  own submissions list **only when you decline** — an approval's note is
  treasurer-eyes-only (it's your working note, not member-facing copy).

Either way the member gets notified with your decision (and your note on a
decline), and their own list of past submissions — visible below their
"Report missing history" form — updates to show the outcome. A member is
capped at 10 outstanding pending submissions at a time (a guardrail against
accidentally flooding the queue) — decide the backlog and they can submit
more.

---

## Settings tab

Per-academic-year settings, in two tables:

- **Dues** — for each year, the three tier amounts (pre-cand / candidate /
  analyst).
- **Tuition** — for each year, the annual amount and the **decision due
  date** (defaults to August 31, the day before the year starts).

The current year is marked. Editing a past year does **not** retroactively
change anyone's recorded charges or payments — it only affects new charges
and reminders going forward.

Below the tables, **Reminder cadences** sets how often the website emails
reminders to unpaid members and undecided students (in days; default 7).
Applies to the current year; future years inherit it on rollover.

> A new academic year is set up automatically each September, inheriting
> its amounts and cadence from the previous year — so changes you save
> here carry forward.

---

## Exports tab

- **All transactions CSV** — every payment with member, amount, status,
  method, date, and Stripe reference. Good for bookkeeping or sharing with
  the board.
- **Member balances CSV** — every member's obligation, paid total, and
  balance on the unified ledger — the export version of the Accounts tab.

Per-event registration rosters aren't here — they live on each event's
page (open an event under **Events** or **Program** and use its "Roster
CSV" link).

---

## Things you don't have to do (the system handles them)

- **Recording Stripe payments** — a payment made on the site lands on the
  Payments tab within seconds of Stripe taking the money; you never fetch
  or import anything. Overnight, every payment still sitting at Pending is
  re-checked against Stripe and settled either way, so a payment can't go
  missing just because a message from Stripe went astray. (Payments taken
  **outside** the site — the old Typeform links — are the exception: those
  are imported by the web coordinator on request.)
- **Issuing receipts** — automatic when a Stripe payment succeeds (or when
  you click **Record an offline payment** / **Mark paid**).
- **Sending payment-success emails** — same.
- **Minting most charges** — dues and tuition charges are minted
  automatically from the tier tables and each student's tuition decision;
  registration charges mint when a registration settles. **Sync charges**
  on the Accounts tab is only for catching up a charge that should exist
  but hasn't been minted yet.
- **Creating next year's academic period** — set up automatically so you
  can plan ahead in Settings.
- **Sending reminders** — sent on the cadence you set in Settings.
- **Blocking double-payment** — the `/dues/` and `/tuition/` pages check
  for an existing payment before starting a new one.

---

## When to ask the Web Coordinator for help

- Bulk operations across many records (e.g. correcting a whole year's data
  once bank records arrive).
- Anything that looks broken (a number doesn't add up, an email bounced).
- Setting up a new treasurer account (when you transition out).
- Anything you'd like to do that this admin doesn't yet handle.
