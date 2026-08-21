# Removing a registration

Task #627. Design date 2026-08-21.

## The question

Faculty asked for a registrant to be taken off a seminar. There is no button
anywhere that does it.

The Registration Admin console (`/admin-tools/registrations/`, task #470) can
approve, decline, comp and annotate, and its own guide tells the registrar that
cancellations are *not* theirs:

> **Refunds and cancellations**: the member's own confirmation page
> (self-service Stripe refund) or the Treasurer Admin.

Both of those are the wrong hands. The member's confirmation page needs the
member to act, and they have not asked to leave — someone else decided they are
leaving. The Treasurer Admin refunds a *payment*; it has no notion of releasing
a place, and for a registration awaiting payment there is no payment to act on.
So the only route left is editing the row in the Django admin by hand, which
moves the status and nothing else: no charge voided, no pricing-code use
returned, no open Checkout session expired, no word to the member.

## What exists already

Almost all of it. The gap is an entry point, not a mechanism.

- `Registration.cancel()` is the state machine: `awaiting_payment` and `comped`
  go to CANCELLED, `paid` refunds through Stripe and goes to REFUNDED, an
  already-cancelled row is a no-op. It expires any open Checkout session (the
  #561 hazard — a stale tab paying for a place that no longer exists) and
  returns the pricing-code use.
- `payments.charges.void_registration_charge` squares the books, deliberately
  including treasurer-adjusted rows.
- `payments.refund.refund_payment` issues the Stripe refund;
  `PlanRefundRequiresTreasurer` refuses when more than one payment settled the
  registration, because someone who attended four of ten sessions is a
  pro-rating conversation, not an arithmetic (§4.1).
- `registrations.views.cancel_registration` is the member-facing orchestration
  of all of the above, including the email.
- `registrations/services.py` is the established home for staff side-effect
  chains shared by more than one surface (`comp_registration`,
  `release_pending_approvals`).

## One state machine, not two

`cancel()` conflates two decisions that the registrar has to make separately:
*release the place* and *return the money*. The chosen behaviour (Rico,
2026-08-21) is that the tool asks and never guesses.

So `cancel()` gains one keyword:

```python
def cancel(self, *, refund: bool = True):
```

The default preserves the member path exactly, and `refund=False` on a PAID row
sets CANCELLED without calling Stripe. Writing a second, parallel cancel for
staff was rejected: two implementations of one state machine drift, and this
repo has been bitten by precisely that (#532's dead
`changed_reviewable_fields()` disagreeing with live code, #568's title stored
twice).

The keyword also does load-bearing work beyond the obvious. The
`PlanRefundRequiresTreasurer` guard lives *inside* the refund branch, so
`refund=False` skips it — which is what makes a payment-plan registration
removable at all. Today a plan registration cannot be cancelled by anyone
without a treasurer first settling the money, so the place stays occupied while
the conversation happens.

## The service

`registrations/services.py::remove_registration(reg, by, *, refund, reason)`,
beside its two siblings. It orchestrates and implements nothing:

1. Guard — a row already CANCELLED, REFUNDED or DECLINED is a no-op.
2. Record what money has settled *before* the status moves (SUCCEEDED payments
   on the registration), because afterwards the reading changes.
3. `reg.cancel(refund=refund)`, catching `RefundError` and
   `PlanRefundRequiresTreasurer` — a refund the site cannot issue must not stop
   the place being released. It falls back to `cancel(refund=False)` and the
   money becomes the treasurer's.
4. `void_registration_charge`.
5. The dated `staff_notes` audit line (REG-14), naming who, the surface, and
   whether money was refunded or left.
6. The member notification.
7. The treasurer handoff, when settled money was left unrefunded.

It returns whether the row was removed, whether a refund was issued, and
whether the treasurer now owns something — so the view builds its message from
what actually happened rather than from a copy read beforehand (#485, #561,
#564).

## Status, and what follows from it

Refunded → REFUNDED. Everything else → CANCELLED.

Both are already in `Registration.INACTIVE_ROSTER_STATUSES`, so the person
drops off the faculty roster, the roster CSV and the seminar's Workspace, and
loses `access_info` — which is the whole point of the button and needs no new
code. Both are also excluded from the `registrations_one_active_per_user_event`
partial unique constraint, so a removal never bars a re-registration that is
meant to happen.

## The money that isn't refunded

The charge is voided in every case. For a PAID row removed *without* a refund
that deliberately leaves the member holding registration-category credit: they
paid, the obligation is gone, and under the category-scoped ledger (#473) that
credit is visible in the right bucket on the Accounts tab and their own
statement. That is the honest reading, and it is the signal the treasurer acts
on.

Leaving the charge open instead was rejected — the books would then assert that
the member owes for a place they do not hold.

It is never silent. A removal that leaves settled money notifies the Treasurer
`StaffRole` holders (bell + email), mirroring `plan_cancel_needs_treasurer`,
including its warning when the role has no holder so the handoff cannot vanish.

Three cases cannot be refunded by the site and so are not offered the choice at
all — the dialog states that the treasurer settles the money:

- an offline payment (no `payment_intent` to refund against);
- a payment plan;
- more than one succeeded payment, plan or not.

Where a refund *is* possible, the default is **remove without refunding**. A
Stripe refund cannot be un-issued; leaving the money is recoverable in one
click from the treasurer's existing screen. The reversible default wins.

Partial and pro-rated refunds stay out of scope. They are the treasurer's
judgment, on the treasurer's screen, exactly as `PlanRefundRequiresTreasurer`
already says.

## What the member is told

Always, with no opt-out. A place disappearing from someone's account with no
word is the failure this feature must not ship.

`send_cancellation_email` is reused — its copy is already passive ("has been
cancelled"), so it fits a removal the member did not ask for — and gains two
things:

- the registrar's optional `reason`, included when given;
- suppression of its closing line, *"If you'd like to register again, you can
  do so at…"*, on any staff removal.

That last is not a detail. Inviting someone the faculty just removed to
register again is the one thing the copy must not do, and the tool cannot tell
a member who withdrew from a member who was withdrawn. Someone who is meant to
come back will ask; the line is dropped for both.

The bell row comes free: `notifications.registration_cancelled` already
dispatches through the notification chokepoint.

## Surface

One icon button and one `<dialog>` in
`registrations/templates/registrations/registrar/_row_actions.html`, which the
Registrations list and the needs-attention strip both include — so they get it
together and cannot diverge. One `registrar_remove` POST view,
`registrar_required`-gated, `_back(request)` preserving the list's filters.

Shown for PENDING_APPROVAL, AWAITING_PAYMENT, PAID and COMPED; absent for the
three terminal statuses. Remove sits alongside Decline rather than replacing
it: Decline is the faculty's judgment on a request, carrying its own reason and
its own email; Remove is administrative and applies whatever the row's history.

No `disabled` attribute anywhere near the submit button — `submit-guard.js`
covers the form automatically and a disabled submitter is dropped from the POST
(#545).

The Django admin and the faculty roster are deliberately untouched. The service
is written so a faculty-facing variant can be added later without reopening the
chain, but faculty do not own the refund decision and this task does not give
it to them.

## Documentation

`core/docs/registrar-guide.md` gains Remove in its row-action list, and its
*"What lives elsewhere"* section is corrected — it currently sends the
registrar away for exactly the thing they can now do.

## Testing

Test-first, in `registrations/test_removal.py`:

- awaiting payment → CANCELLED; no Stripe call; pricing-code use returned; open
  Checkout session expired; member emailed; treasurer *not* notified.
- comped → CANCELLED; the WAIVED charge voided.
- paid, refund chosen → `refund_payment` called once; REFUNDED; charge voided;
  the refunded amount reaches the email.
- paid, refund declined → CANCELLED; Stripe never called; charge voided;
  treasurer notified; the member's registration-category balance reads as
  credit.
- payment plan → the refund option is never offered; the place is released; the
  installment schedule survives for the treasurer; no further nudges, because
  `send_registration_reminders` filters plan rows on `status=PAID`.
- offline payment with a refund requested → `RefundError` is caught, the place
  is still released, and the treasurer is notified.
- already CANCELLED → no-op, no second email.
- a non-registrar gets 404 (the console's denied-user convention).
- email copy: the reason appears when given; the "register again" line does not.
- `cancel()` with no keyword still refunds — the member path is unchanged.

## Not in scope

Partial refunds. Bulk removal. Barring a removed member from re-registering.
A faculty-facing button. Any automatic consequence for the event (a released
place does not promote anyone from a waitlist — there is no waitlist).
