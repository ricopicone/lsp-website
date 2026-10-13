# Per-class billing (REG-6) — design

Task #811, found while triaging #810 (Matthew Seidman, *Beyond Principle*,
event 25). Approved in conversation with Rico, 2026-10-12.

## Problem

Some faculty bill per class ($25/class, with the number of sessions not yet
known). The site can only sell a place in the whole seminar, so a $25
fixed-price code enrolled four people for the entire year. REG-6 ("per-class
versus whole-seminar payment options, configurable per seminar") is a Core
requirement that was only scaffolded: `PriceTier.session`,
`Registration.sessions` and `Profile.default_billing_mode` exist and nothing
reads them.

The constraint above all others: **the existing system (tuition coverage,
payment plans, codes, comps, removal, the ledger) is intricate and must not
break.** The design is shaped by that.

## Decisions (Rico, 2026-10-12)

1. **Attendance-based.** A per-class member is billed for the classes they
   attend. Optional per seminar; most seminars will never use it.
2. **Auto-attendance:** detected from the site's video room where the event
   meets there (online + in-site room); otherwise (in person, Zoom, hybrid)
   every enrolled member is presumed present.
3. **3-day correction window** after each class: faculty/conveners mark
   anyone, a student marks themselves; a faculty mark locks the student's.
   Both get one notice when attendance is recorded.
4. **Billing:** each class is billed as its window closes (one Charge per
   class); members are notified in a **weekly batch**.
5. **Post-billing removal:** within **14 days** of billing, faculty/conveners
   may mark a member absent, which voids that class's charge — only while the
   charge is still entirely unpaid in the ledger. Otherwise it is the
   treasurer's call. The reverse (absent → present, billing then) is allowed
   in the same window.
6. **Billing mode is part of the price.** It is chosen on the proposal, the PC
   approves it, and it changes only along whatever route a price change
   travels (the change-review loop). It locks once anyone is registered.
   Widening the review loop to imported program events is a **sibling task**,
   not this one.
7. **Codes read per class** on a per-class event; installments and
   full-price (plan-only) codes are refused there.
8. **#810:** convert Matthew's registrants in place; bill only classes from the
   conversion date onward; the $25 each already paid becomes credit.
9. `Profile.default_billing_mode` stays unused.

## Architecture: parallel rows existing code cannot see

The safety property is isolation. A per-class registration is, to every
existing path, an ordinary **$0, enrolled (PAID)** registration. Its money
flows through new rows that the existing money paths cannot see:

- **`events.ClassAttendance`** — one row per (registration, session):
  present/absent, `source` (detected / presumed / faculty / student), who
  marked it and when, `faculty_locked`, `recorded_at`, `billed_at`,
  `outcome` (charged / absent / covered / comped / no_charge), `notified_at`.
  Unique on (registration, session). `session` FK is CASCADE; a billed row is
  protected by its Charge (below).
- **`Charge.class_attendance`** (new nullable FK, PROTECT) — a billed class is
  an ordinary `Charge` of category *registration* with **`registration`
  left NULL**. New constraint: one non-void charge per attendance row.
  Because `registration` is NULL, `mint_registration_charge`,
  `void_registration_charge`, `charge_unique_registration`, refunds and
  removal never see a class charge.
- **`Payment.per_class_registration`** (new nullable FK, PROTECT) — paying a
  balance is a Payment of type *registration* pointing here, with
  `Payment.registration` NULL, so `complete_payment`'s registration branch
  (status flip, settle-time charge, "you're registered" mail) never fires.
  This follows Payment's existing one-FK-per-obligation pattern.
- **`Registration.per_class_rate`** (nullable Decimal) — the member's rate
  per class, resolved at registration. Non-null ⇔ per-class registration
  (`Registration.is_per_class`). `quoted_amount` stays 0.
- **`Event.billing_mode`** (`whole` default / `per_class`) and
  **`Event.per_class_since`** (datetime, set when the mode becomes per-class;
  the recording pass only records classes ending after it).

The ledger needs no change: class charges are registration-category charges,
so the account balance, the statement and `audit_ledger` include them as they
are. **Amended after review:** a seminar's "open balance" (the panel, the Pay
button, faculty un-billing, the coverage void) is computed from *that
registration's own* money — payments linked by `per_class_registration` or
`registration` — swept oldest-class-first (`per_class.class_coverage`), not
from the member-wide registration bucket. Reading the bucket let imported
registration credit (which carries no charge) silently "pay" classes, and let
a class payment land on an older seminar's plan charge so the member was asked
to pay again. The #810 $25 is held through `registration=reg`, so it still
covers the first class.

Rejected: a single growing registration Charge (rewrites a money row weekly;
no per-class row to void), and a child Registration per class (breaks the
one-active-registration constraint, roster, access and console counts).

## Enrollment and pricing

- The price spec (`events/price_spec.py`) carries `billing_mode`; labels read
  "$25 per class" / "Sliding, at least $10 per class". The proposal form
  offers it beside Free/Fixed/Sliding; `EventProposal.approve()` mints it.
  The edit form carries it through the existing price review route. A change
  of mode while the event has any active registration raises
  `UnrepresentablePricing`-style refusal with a "contact the Web Coordinator"
  message.
- Registering on a per-class event: same form, tiers, sliding box, code box,
  gates. `resolve_price` (with tuition coverage **ignored**) yields the rate,
  stored in `per_class_rate`; `quoted_amount=0`; status PAID, or
  PENDING_APPROVAL under approval. No Stripe at registration; no plan built.
  The confirmation page/email explain per-class billing.
- **Tuition coverage is decided per class at billing time**: a class is not
  charged when the tier is `covered_by_tuition`, the registration carries no
  code, and the member is tuition-current for the **event's** academic year.
  Two hooks beside the existing coverage functions:
  - recording a covering decision (member and treasurer paths) voids that
    year's entirely-unpaid class charges (mirrors #561);
  - recording SKIPPING on the member path bills that year's classes recorded
    as covered (mirrors #485). Staff paths never retro-bill.
- **Codes:** amounts read per class. `installments > 1` and `FULL_PRICE` are
  refused on per-class events (form + server). Applying a code to an existing
  per-class registration updates `per_class_rate` for classes not yet billed;
  it never re-quotes.
- **Comp:** the registrar's comp accepts a per-class PAID row and makes it
  COMPED; billing skips COMPED. Already-billed classes stay for the treasurer.
- Staff may edit `per_class_rate` in Django admin (future classes only).

## Attendance timeline

Runs as a pass of the existing 5-minute `send_meeting_reminders` timer (no
host change), in `events/per_class.py`:

1. **Record** — for each ended session of a per-class event, ending after
   `per_class_since`, not yet recorded: a row for every PAID/COMPED
   registration created before the session ended. Detection: if the event is
   online and `uses_insite_room` and video is enabled, ask Daily which member
   ids joined the room between start−30m and end+30m (requires `mint_token`
   to set `user_id`); present iff joined. If Daily fails, retry each run for
   24h, then presume present and say so in the faculty notice. Otherwise
   presumed present. Notices: one to `offering_leads`, one to each
   registrant (new member-adjustable category `CLASS_ATTENDANCE`).
2. **Window** — until session end + 72h: faculty/conveners mark anyone;
   a student marks themselves unless `faculty_locked`. Each change appends
   to an audit note.
3. **Bill** — when the window closes: present + PAID + not covered + rate > 0
   → mint the class Charge (effective date = the class's school-local date);
   otherwise record the outcome. Idempotent by constraint.
4. **Notify** — weekly (Monday, school time), per member per seminar: classes
   billed since the last notice, amount, open balance, Pay link.

UI: an Attendance section on the Workspace Roster tab (per-class events
only); a "Your classes" panel on the seminar's Workspace/event page with
corrections in-window, balance and Pay.

## Payment

Pay button → Stripe Checkout for the open balance, itemised by class.
`Payment(type=registration, per_class_registration=reg)`. A new small branch
in `complete_payment` sends the receipt + a "payment received" email. Starting
a payment expires open Checkout sessions for the same registration's balance.
Offline: the treasurer's existing record-a-payment sweeps the same way. No
automatic consequence for an unpaid balance; no extra nagging.

## Corrections after billing

Within 14 days of `billed_at`, faculty/conveners may:
- present → absent: only while that charge's ledger state is entirely open;
  voids it with an audit note; member notified of the new balance;
- absent → present: bills the class then.
The treasurer can void/waive/reopen any class charge from the statement at
any time (existing actions).

## Skip-list (each pinned by a test)

| Path | Behaviour for a per-class registration |
|---|---|
| `coverage.covered_registrations` / `apply_coverage` / `bill_skipped_coverage` | excluded |
| `apply_code` / `auto_apply_pinned_code` | update `per_class_rate` only |
| plan building / code minting | never a plan; installments refused |
| `Registration.cancel()` | never auto-refunds; billed classes stay owed |
| registrar removal (#627) | no refund option; message notes open balance |
| `comp_registration` | accepts PAID per-class → COMPED |
| price spec / proposal / edit / review | carry `billing_mode`; lock once registered |
| session delete / `generate_sessions --clear` | refused when a billed class exists (PROTECT) |
| `mint_token` | also sets `user_id` |

Unchanged by construction, pinned anyway: registration-charge mint/void and
its constraint; `complete_payment` registration branch; refund webhook;
`send_registration_reminders`; access/room/joining/reminders/roster;
registrar counts (a "Per class" chip on the roster).

## #810 conversion

`manage.py convert_event_to_per_class <slug> --price … --bill-from DATE
[--dry-run]` — the only route past the lock. Sets mode, `per_class_since`,
price; re-resolves each active registration's rate with its existing code;
sets `quoted_amount=0`; voids its whole-seminar charge (its payment becomes
credit); staff note; member notice. Refuses on any registration on a plan or
any code with installments > 1. Dry-run prints the per-registrant effect.
Run on prod as dry-run first; the real run waits for Rico.

## Not in scope

Widening the review loop to imported program events (sibling task); a
per-faculty default mode; picking specific sessions; per-session price tiers;
automatic consequences for unpaid balances.
