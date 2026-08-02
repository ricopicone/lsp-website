# Skipping tuition after consuming coverage re-bills the event fees

**Task:** #485 — follow-on to #484. "I don't think declines will be common, but I
want to understand what happens in that case. Essentially I think they should be
given the same skip/pay tuition option at that point, then if they skip they
should owe individual event registration amounts or the full tuition amount
depending on their choice."
**Date:** 2026-07-29

## Problem

Task #484 gave a pending payment-plan request the same event coverage a
commitment gets. That opened a branch nobody owns: coverage consumed, year not
paid.

What a Board **decline** does today, traced end to end:

1. `tuition_plan_decide` sets the application DECLINED and **deletes** the
   `PLAN_REQUESTED` enrollment row (`payments/views_plan_review.py:90`).
2. That delete fires `post_delete` → `sync_tuition_charges`, which **voids that
   year's tuition charge** (`payments/charges.py:156`). No tuition is owed.
3. The member is notified and, with no row on file, the Account tab shows the
   decision form again — pay, apply again, or skip. **The skip/pay choice the
   task asks for already happens**, and the broad gate blocks new registrations
   until they choose.

The two branches then diverge:

- **They commit or pay in full** → the same signal *revives* the tuition charge,
  the full year is owed, and the events they took free are legitimately covered.
  **Already correct; no work needed.**
- **They skip** → nothing is owed for those events. A covered registration is
  created with `quoted_amount=0` and **no Payment and no Charge**
  (`registrations/views.py:166`; `mint_registration_charge` requires
  `amount > 0`), so it is invisible to the ledger, and SKIPPING is exempt from
  tuition charges (`payments.charges._owed_periods`). They keep the events for
  free.

**This is not specific to declines.** Every route from consumed coverage to an
unpaid year has the same hole, most obviously a member who records COMMITTED,
registers free, then re-records SKIPPING. Declines are the rarer case; the
mechanism must serve both.

## Decision

**Recording SKIPPING for a year re-bills the tuition-covered registrations in
that year at the regular fee. Recording any paying decision un-bills them.**

Four decisions from the 2026-07-29 conversation, each with the alternative that
lost:

1. **Re-quote the registration; do not mint a bare charge.** Setting
   `quoted_amount` and `status=AWAITING_PAYMENT` lights up the existing
   **"Pay →" Stripe button** on the confirmation page
   (`registrations/templates/registrations/register_confirm.html:62`), enrolls
   them in `send_registration_reminders`, and mints the `Charge` at settle via
   the ordinary `mint_registration_charge` path. A bare `Charge` would show on
   the statement but **cannot be paid** — the member-facing payment endpoints
   are dues, tuition-in-full, installments, donations, and per-registration
   checkout, nothing else — so every case would need the treasurer to invoice
   and hand-record.
2. **Auto-bill on the member's own confirmed action, not a review queue.** The
   member is warned first and confirms; their click is the review. A treasurer
   queue was considered and rejected as something nobody may visit.
3. **The fee is `base_amount`, or `minimum_amount` for a sliding tier.** A
   covered tier is the same tier non-paying members buy, so its `base_amount`
   *is* the regular fee. On a sliding tier a skipping member would have chosen
   their own figure at or above the floor, so assume the floor rather than the
   top.
4. **Access loss is accepted.** `has_paid_registration` gates `show_access_info`
   and the video Join button (`events/views.py:116`), so a re-billed
   registration loses access until settled, mid-seminar included. The route back
   is short and does not require money: recording "I plan to pay tuition"
   un-bills the registration and restores access immediately.

## Design

### `payments/coverage.py` (new)

One small module, four names. It owns the question "what did tuition coverage
give this member in this year, and what is it worth?" and nothing else.

- `REBILLED_EXPLANATION` — module constant, the `quoted_explanation` written on a
  re-billed registration. It is also the **marker** `unbill` matches on, exactly
  as the existing `"Covered by tuition (tuition-paying member, REG-4)"` string
  identifies a covered registration. Pinned by a test so it cannot drift. No new
  model field and no migration.
- `retro_amount(tier) -> Decimal` — `tier.minimum_amount` when
  `tier.sliding_scale`, else `tier.base_amount`.
- `covered_registrations(user, period)` — the member's registrations whose event
  falls in `period` (via `payments.ledger.period_for_event`, the same anchor the
  registration gate uses), with `price_tier.covered_by_tuition=True`,
  `pricing_code__isnull=True`, `quoted_amount == 0`, and status PAID or
  PENDING_APPROVAL. The exclusions are deliberate: a **comp** is status COMPED
  and already charge-backed by `mint_comped_charge`, and a **pricing-code
  freebie** is not tuition coverage. CANCELLED and REFUNDED rows are out.
- `bill_skipped_coverage(user, period) -> list[Registration]` — for each of the
  above: `quoted_amount = retro_amount(tier)`,
  `quoted_explanation = REBILLED_EXPLANATION`, and an audit line appended to
  `staff_notes` (the REG-14 override trail). Idempotent: a row already carrying
  the marker is skipped.

  **Status moves only for a PAID row** (→ AWAITING_PAYMENT). A PENDING_APPROVAL
  row keeps its status and only has its amount rewritten, because
  `Registration.approve()` already routes on the amount — `$0` → PAID, nonzero →
  AWAITING_PAYMENT — so flipping it directly would skip the faculty approval it
  is waiting for.
- `unbill_skipped_coverage(user, period) -> list[Registration]` — the reverse,
  for rows carrying the marker that are **still unpaid**. `quoted_amount` back to
  `0`, the coverage explanation restored, another audit line, and status back to
  PAID only for the rows this function moved (a PENDING_APPROVAL row again keeps
  its status). A row the member actually paid is left alone: money that arrived
  is a refund conversation for the treasurer, never a silent unwind.

### `payments/views.py` — `tuition_decision`

The only wiring point.

- **status == `skipping`** and `covered_registrations(user, period)` is
  non-empty and the POST lacks `confirm=1` → render
  `payments/templates/payments/skip_confirm.html`: each event, its fee, the
  total, and a form that re-POSTs the same decision with `confirm=1`. POST-only,
  no JS, mirroring the task #295 certify-or-submit dialog. Nothing is recorded on
  this pass.
- **status == `skipping`** with `confirm=1` (or no covered registrations) →
  record SKIPPING as today, then `bill_skipped_coverage`, then notify.
- **any other status** (`committed`, plan request) → record as today, then
  `unbill_skipped_coverage`. This is what makes "commit to pay and get access
  back without paying" work.
- `tuition_pay_in_full` and `tuition_setup_plan` need no wiring: neither moves a
  status away from SKIPPING.

Staff paths deliberately do **not** auto-bill: Django admin, the treasurer's
inline set-status, `backfill_tuition_status`, and the importers. A historical
backfill that retro-billed years of events would be a disaster, and the
treasurer's discretion is the point (do-not-over-automate). The treasurer guide
says so.

### Notifications and copy

- One notification to the member after billing (`ACCOUNT_UPDATES`): N
  registrations now require the regular fee, with the total and a link to their
  Account tab. Without it the only signal is a page that silently changed.
- `register_confirm.html` gains a line for a re-billed registration explaining
  *why* a covered place now wants money, and that recording a tuition commitment
  restores coverage. "Awaiting payment" with no stated cause is the failure mode
  to avoid.
- `payments/notifications.py::notify_plan_application_decided` — the decline body
  added in #484 ("we'll be in touch about settling it") is replaced with the
  concrete consequence: commit and the events stay covered, skip and the regular
  fees apply.

### Member-facing copy rules

Commas, not em dashes (2026-07-06 convention). DaisyUI semantic tokens only.

## Tests

- `retro_amount`: flat tier returns `base_amount`; sliding tier returns
  `minimum_amount`.
- `covered_registrations` scoping: includes a covered $0 registration in the
  period; excludes one in a different academic year, a COMPED registration, a
  $0-by-pricing-code registration, and a CANCELLED one.
- Skip with coverage consumed → each registration is AWAITING_PAYMENT at the
  right amount, `needs_payment` is True (so the Pay button renders), and
  `staff_notes` carries the audit line.
- Skip then commit → un-billed to `quoted_amount == 0` and status PAID, so the
  event page's access gate (`status in (PAID, COMPED)`, `events/views.py:65`)
  passes again.
- A PENDING_APPROVAL covered registration is re-quoted but **stays**
  PENDING_APPROVAL, and approving it afterwards lands on AWAITING_PAYMENT.
- Skip, member pays the fee, then commits → the paid registration is untouched.
- The confirm page: GET-equivalent first POST records nothing and lists every
  event with its fee and the total; the `confirm=1` POST records and bills.
- Billing is idempotent: running it twice does not double the amount.
- `REBILLED_EXPLANATION` is pinned so `unbill` cannot silently stop matching.
- A member with no covered registrations still records SKIPPING in one POST, no
  confirm page.

## Out of scope

- Any treasurer-side "bill this member's covered registrations" button. If the
  need shows up, it is a thin wrapper over `bill_skipped_coverage`.
- Refunds when a member pays a re-billed fee and then commits to tuition. Left
  to the treasurer, by design.
- A generic "pay my balance" endpoint for bare charges. It would be the
  alternative to re-quoting, and re-quoting won.
- Sweeping earlier years where coverage was consumed but the year ended up
  skipped. Scope is the year whose decision is being recorded.
- Preserving event access while re-billed, and any new field on `Registration`
  to support that. Access loss is the accepted consequence.
