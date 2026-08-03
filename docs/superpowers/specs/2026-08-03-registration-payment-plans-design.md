# Payment plans for an individual seminar or reading group

**Task:** #501 — "I think the idea would be to make a payment plan one of the
code minting options for faculty/conveners of a seminar or reading group. Look
into the feasibility and how clean this feature would be."
**Date:** 2026-08-03

## Problem

Seminar and reading-group fees run $50–$900 (`mint_program_tiers.py` — a
$60/session seminar over fifteen sessions is $900). Faculty already hold three
discretionary levers for a member who can't meet that: a percent-off code, a
fixed-price code, and a sliding floor. All three answer the same question —
*how much* — and none answers the other one a member actually asks, which is
*when*. The school's own tuition already has the answer for the annual case (a
payment plan: the full amount over 2 or 9 installments, never a reduced total);
nothing carries it down to a single event.

The mechanism has to stay discretionary. Faculty use sliding-scale and "none
turned away for lack of funds" pricing, and the school asked explicitly that
automation not remove human judgment (architecture §4.1). A blanket
"installments available on every event" would be the wrong shape.

## Feasibility

Most of what a registration payment plan needs is already built, which is why
this lands as a medium feature rather than a large one:

- **`payments.Charge` already models one debt per registration.** It carries a
  `registration` FK with a unique-when-not-void constraint
  (`payments/models.py:726`), so a $500 registration is one $500 charge however
  many payments settle it.
- **The ledger already reports partial coverage.** `_charge_states` returns
  `"paid" | "partial" | "unpaid"` per charge plus the covered amount
  (`payments/ledger.py:83`). A part-paid registration therefore reads correctly
  on the member's Account tab, the treasurer's statement, and the balance
  reminder with no new accounting.
- **`Payment` already points at a registration** and nothing constrains a
  registration to one payment (`payments/models.py:149`).
- **`complete_payment` already flips `AWAITING_PAYMENT → PAID` on the first
  successful payment** (`payments/operations.py:42`) — precisely the access
  semantics a plan wants, needing no change.
- **`TuitionInstallment` + `_build_installment_schedule` +
  `plans.due_installment` + the task #494 nudge plumbing** is a shipped, tested
  template for the schedule half.
- **The delinquency lever exists and is human.** A treasurer flips
  `Profile.seminar_access_suspended` from the member account page
  (`payments/views.py:1091`), which excludes the member's registrant-derived
  seminar workgroup membership. Nothing automatic sets it, and nothing here
  will.

## Decision

**A pricing code may carry an installment count. Redeeming it splits the fee
into that many hand-paid Stripe payments; it never changes the total.**

Five decisions from the 2026-08-03 conversation, each with the alternative that
lost.

### 1. The schedule is orthogonal to the discount, not a fourth pricing mode

The task proposed a plan as one of the code-minting *options*, which reads
naturally as a fourth `PricingCode.Mode`. Rejected: `pricing_mode` owns *how
much* (`percent_off`, `fixed_amount`, `sliding_floor`) and its companion field
`amount_or_percent` is money or percent in all three. A mode meaning "in three
payments" would have to reinterpret `amount_or_percent` as a count, in the one
function documented as a place where a bug costs money
(`events/pricing.py:9`), and it would make "20% off, payable in three"
inexpressible — collapsing two independent axes into one.

`PricingCode.installments` is therefore a separate `PositiveSmallIntegerField`
defaulting to `1`. **Default 1 means every existing code and every existing
pricing test is unaffected**, and `1` is not a special case in the code — it is
the ordinary pay-in-full path.

The rejected options also included a per-event `allow_payment_plan` flag
(blanket, not discretionary) and a per-registrant faculty button after the
fact (most discretionary, but a whole new roster surface, and it can't be
extended *before* someone registers).

### 2. `Mode.FULL_PRICE` fills the gap the orthogonal field opens

With the schedule split off, a faculty member offering "full price, payable in
three" has no discount to state, but `pricing_mode` is required. New mode
`FULL_PRICE` ("Full price — payment plan only"), for which
`amount_or_percent` is unused and the resolver returns the tier's own
`base_amount`.

Rejected: making `pricing_mode` blank-able (adds a null branch to
`_apply_code`, again the money-critical function), and telling faculty to mint
a `fixed_amount` code at the current base price (hardcodes the fee into the
code, so a later tier change leaves the code silently quoting a stale price).

### 3. The site sets the dates; faculty set only the count

The tuition schedules are academic-year anchored (Sept + Feb, or monthly
Sept–May). Seminars start on arbitrary dates and run six to fifteen sessions,
so that shape does not transfer.

The code carries a count. On redemption the site divides the fee evenly, puts
the rounding remainder on the **final** installment so the sum is exact (the
rule `_build_installment_schedule` already uses), sets installment 1 due
immediately, and spaces the rest **monthly from the registration date**.

Rejected: spreading due dates across the event's own session run (requires
sessions to be scheduled before the code is minted, and compresses badly for
short events); faculty authoring amounts and dates by hand (faculty mint a code
in about ten seconds today, and this would make every code bespoke); and the
member choosing the count from an allowed range (an extra step in a register
flow that is currently one form).

The treasurer can hand-edit a schedule afterward in Django admin, exactly as
they can for tuition today.

### 4. Self-service cancel refuses on a plan and routes to the treasurer

`Registration.cancel()` today refunds `.first()` succeeded Stripe payment and
flips to REFUNDED (`registrations/models.py:135`). With three installments it
would refund one of them and call the registration refunded.

A plan registration therefore **refuses** self-cancel, reusing the existing
`RefundError` path that `cancel_registration` already handles with a clean
member-facing message (`registrations/views.py:266`), reworded to name the
treasurer, plus a notification to them.

This is honest about what the site can decide. Someone who attended four of ten
sessions and stops paying is a pro-rating conversation, not a full refund — and
pro-rating is exactly the kind of judgment §4.1 reserves for a person.

**Note this is a latent bug today, not one this feature introduces.** Any
registration carrying two succeeded payments already under-refunds. The guard
keys off "more than one succeeded payment, or an installment schedule exists",
so it closes both.

Rejected: refunding every installment automatically (a member who sat through
half a term gets everything back with no human in the loop), and a
date-based rule refunding freely until the first session (the site can evaluate
it, but it still auto-refunds someone the day before a term starts after
faculty have planned around them).

### 5. Faculty see that a plan was taken up, not how it is going

The roster shows a neutral **"On a plan"** chip. No amounts, no
current-versus-behind distinction.

Faculty issued the plan, so the chip tells them it was used. How it is going is
between the member and the treasurer, and the roster is a surface faculty
export to CSV and read in class. Rejected: showing "$200 of $500, 2 of 3 paid"
(puts a member's financial standing on a downloadable roster), and showing
nothing at all (the faculty member who granted the terms can't tell whether
they were taken).

## The consequence worth stating plainly

**`Registration.status == PAID` stops meaning "settled" and starts meaning
"enrolled."**

The ledger is untouched by this — it reads charges and payments and never reads
registration status, so a plan member's balance, statement, and balance
reminder are all correct from day one. What shifts is the *reading* of
`PAID` on the surfaces that display it: the registrar console's per-status
counts and the roster CSV now describe enrollment rather than money. Both are
left as they are; the "On a plan" chip is the disclosure.

This is not a new idea in the codebase so much as a sharpening of one:
`COMPED` has always meant "enrolled, no money", and `PAID` on a
`covered_by_tuition` registration has always meant "enrolled, money accounted
elsewhere".

## Design

### Data model

**`events.PricingCode.installments`** — `PositiveSmallIntegerField(default=1)`,
help text "1 = pay in full at registration." Validated ≥ 1 and ≤ 12 in
`clean()`.

**`events.PricingCode.Mode.FULL_PRICE`** — `"full_price"`, "Full price —
payment plan only". `amount_or_percent` is unused for this mode; the form
hides it and the model stores `0`.

**`payments.RegistrationInstallment`** — mirrors `TuitionInstallment`
(`payments/models.py:561`) field for field:

| Field | Type |
|---|---|
| `registration` | FK `registrations.Registration`, `related_name="installments"` |
| `sequence` | `PositiveSmallIntegerField`, 1-indexed |
| `due_date` | `DateField` |
| `amount` | `DecimalField(8, 2)` |
| `paid` | `BooleanField(default=False)` |
| `paid_at` | `DateTimeField(null=True)` |

`UniqueConstraint(("registration", "sequence"))`, `ordering =
("registration", "sequence")`, and a `mark_paid()` matching its twin.

It lives in `payments`, not `registrations`: every money model lives there, and
its twin is three classes above it.

**`payments.Payment.registration_installment`** — nullable FK,
`related_name="payments"`, mirroring the existing `tuition_installment`.

Two migrations (one per app).

### Pricing resolver

`PriceResolution` gains `installments: int = 1`. `_apply_code` sets it from
`code.installments` and adds the `FULL_PRICE` branch, which returns
`tier.base_amount` with the explanation `f"Full price ${amount} via code
{code.code}."` **The resolver still returns one total.** A plan changes when,
never how much — the same discipline the tuition plan holds (see the
`tuition-assistance-is-the-payment-plan` project memory).

### New module: `payments/registration_plans.py`

Deliberately a sibling of `payments/plans.py` rather than an extension of it.
`plans.py` answers "what does this tuition enrollment owe right now" and is
read by three tuition surfaces; the two share a shape, not a caller.

- `build_schedule(registration, count, *, today) -> list[RegistrationInstallment]`
  — even split, remainder onto the last, first due `today`, subsequent monthly.
  Idempotent: returns the existing rows if any exist.
- `due_installment(registration, today, *, lead_days=LEAD_DAYS)` — oldest
  overdue, else earliest falling due within the lead window. Mirrors
  `plans.due_installment`, including `LEAD_DAYS = 7`.
- `is_on_plan(registration) -> bool` — has more than one installment row.
- `outstanding(registration) -> Decimal` — sum of unpaid installment amounts.

### Registration flow

`_create_registration` (`registrations/views.py:66`) — when
`resolution.installments > 1` and `resolution.amount > 0`, call
`build_schedule` inside the existing atomic block. The registration's
`quoted_amount` stays the **full** fee; `quoted_explanation` gains
", payable in N installments".

The register view then creates the Checkout session for **installment 1's
amount**, not `quoted_amount`. New
`stripe_checkout.create_registration_installment_session(payment)`, modelled on
`create_tuition_session` — product description "Installment 1 of 3 for
<event>".

An event `requires_faculty_approval` builds the schedule at `approve()` time,
not at creation, matching how the pricing code's use is consumed there
(`registrations/models.py:166`).

### Settlement

`complete_payment` (`payments/operations.py:27`) gains one branch mirroring
`_apply_tuition_payment_success`: if `payment.registration_installment_id`,
mark the installment paid. The existing `AWAITING_PAYMENT → PAID` flip is
unchanged and grants access on installment 1.

`mint_registration_charge` (`payments/charges.py:219`) must bill the **full
fee** for a plan registration, not `payment.amount`. Scoped to plan
registrations — a non-plan registration keeps minting exactly what it mints
today, so no historical row's provenance shifts:

```
amount = (registration.quoted_amount if is_on_plan(registration)
          else payment.amount)
```

It is already idempotent per registration, so installments 2 and 3 mint
nothing.

### Paying the rest

New view `registrations:pay_installment`, in `registrations/views.py` beside
the existing `pay_registration` (`registrations/views.py:337`). Owner-only; a
paid installment is a no-op redirect; the body mirrors
`tuition_pay_installment` (`payments/views.py:2554`).

`register_confirm.html` grows a schedule block when the registration is on a
plan: each installment's sequence, due date, amount, and state, with a Pay
button on what is due. Modelled on the tuition Account tab's installment list.

### Reminders

`send_registration_reminders` gains a third kind alongside faculty-approval and
student-payment: registrations that are `PAID`, on a plan, and carry a
`due_installment`. Same `reminded_at` throttle, same `ThrottledSender`, same
`--interval-days`. New email + notification via the existing
`payments/emails.py` + `payments/notifications.py` pattern.

### Cancel

`Registration.cancel()` — before the refund branch, if the registration is on a
plan or carries more than one succeeded Stripe payment, raise
`PlanRefundRequiresTreasurer(RefundError)`. `cancel_registration` catches
`RefundError` already; add a message naming the treasurer for this subclass and
notify them.

### Faculty and treasurer surfaces

- `PricingCodeForm` gains `installments` and the `FULL_PRICE` mode; the code
  list on the faculty event view shows "in N payments".
- The faculty roster shows an "On a plan" chip (no amounts, no CSV column).
- The treasurer's member statement labels the registration charge row "on a
  payment plan" — the partial coverage it already displays supplies the
  numbers.

## Non-goals

- **No autopay.** Every installment is a hand-clicked Stripe Checkout, matching
  the tuition plan (`payment-plan-is-manual-stripe-not-autopay`). No
  Subscriptions, no saved cards, no BNPL.
- **No pro-rating**, anywhere.
- **No faculty-authored due dates or amounts.**
- **No automatic consequence for defaulting.** The lever is the treasurer's
  existing `seminar_access_suspended`, which is human and audited. A member who
  stops paying keeps access until a person decides otherwise, which is the
  behavior §4.1 asks for.
- **No interaction with per-session registration (REG-6).** A plan splits the
  registration's total, whatever produced it.
- **No change to tuition.** `TuitionInstallment` is untouched; the duplication
  between it and `RegistrationInstallment` is accepted rather than abstracted,
  because unifying them would rewrite the load-bearing tuition plumbing shipped
  in #494 for no behavior gain.

## Testing

`payments/test_registration_plans.py` and additions to the existing pricing,
webhook, and cancel suites.

- **Resolver:** a code with `installments=1` resolves byte-identically to
  today; `installments=3` returns the same total plus the count; `FULL_PRICE`
  returns `tier.base_amount`; `FULL_PRICE` combined with `installments=3`
  works; `percent_off` combined with `installments=3` works (the axes are
  independent).
- **Schedule:** $500 in 3 sums to exactly $500 with the remainder on the last;
  due dates are today, +1 month, +2 months; `build_schedule` is idempotent.
- **Charge:** a plan registration mints one `Charge` for the **full** fee at
  first settle, not the installment amount; installments 2 and 3 mint nothing;
  a non-plan registration's minted amount is unchanged.
- **Ledger:** the charge reads `"partial"` after installments 1 and 2 and
  `"paid"` after 3; the member's balance falls by each installment.
- **Access:** the registration is `PAID` after installment 1, and the member
  appears in the seminar workgroup's derived roster.
- **Cancel:** a plan registration raises rather than refunding; a single-payment
  registration still self-cancels and refunds as it does today.
- **Reminders:** a plan registration with an overdue installment is nudged; one
  fully paid is not; the throttle holds.
- **Approval flow:** an approval-gated plan registration builds its schedule at
  `approve()`, and none at all if declined.

## Size

One model, two fields, one new mode, two migrations, one new module, and edits
to roughly ten files. Comparable to task #485. The reason it is not larger is
that the charge-per-registration model, the `"partial"` coverage state, and the
multi-payment `Payment` FK were all already in place; what is genuinely new is
a schedule and one corrected amount.
