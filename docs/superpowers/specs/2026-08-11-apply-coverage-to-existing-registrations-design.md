# Applying tuition coverage to registrations that already exist

Task #561. Design, 2026-08-11.

## The report

Matt Lovett, after his tuition records were corrected: *"They all now say I am
registered but awaiting payment?"*

## What was actually wrong

A registration is priced **once, at creation**. All four of his registrations
are Sept–Oct 2026 events, and both the pricing resolver
(`events.pricing._is_tuition_paying`, task #450 phase A) and the ledger
(`ledger.period_for_event`) anchor coverage on the **event's own** academic
year. So all four belong to **AY 2026–2027** — the year that had not started
yet. Each was created before any AY 2026–27 enrollment row existed (reg#37 on
Jul 28 21:49; reg#96/97/98 on Aug 11 02:31–02:33; the enrollment row was
created Aug 11 08:25), so each correctly stored the regular fee with
`quoted_explanation='Standard All price.'`.

Recording the covering decision afterwards changed nothing about them, for two
independent reasons:

- `coverage.unbill_skipped_coverage` selects **only** rows whose
  `quoted_explanation == REBILLED_EXPLANATION` — the marker
  `bill_skipped_coverage` writes. His rows were identical in every way that
  matters to coverage but carried `'Standard All price.'`, so the restore path
  could not see them.
- The status was changed from the treasurer's surface, and
  `treasurer_tuition_set_status` never calls `coverage` at all — neither
  direction.

Verified on prod before any change: `covered_registrations(AY 26-27)` returned
`[]`, no row carried the marker, and all four resolved to `$0.00 / "Covered by
tuition (tuition-paying member, REG-4)"` when re-quoted. **The AY 2025–2026
change was a red herring** — it could not reach an AY 2026–27 event.

The generalisation: **a member who registers before recording a covering
decision keeps the full quote forever.** Task #485 built the restore as an undo
for its own billing rather than as an answer to "what does coverage owe this
member now", so the one case it could not cover is the one that happened.

## The design

### One predicate, no marker

`payments/coverage.py` gains `apply_coverage(user, period)` and **loses**
`unbill_skipped_coverage`. It selects the user's registrations where the tier is
`covered_by_tuition`, there is no pricing code, `quoted_amount > 0`, the status
is `AWAITING_PAYMENT` or `PENDING_APPROVAL`, and `period_for_event(event) ==
period`.

Replacing rather than adding is the point. Rows carrying `REBILLED_EXPLANATION`
are a **strict subset** of that predicate: `bill_skipped_coverage` only ever
writes the marker onto covered-tier, code-less rows with a positive amount in
those two statuses. Matching on the marker string is precisely what made this
bug invisible, and keeping both would leave the two directions able to disagree
about what coverage bought. `REBILLED_EXPLANATION` itself stays — billing still
writes it, and a test pins the string — but nothing reads it back.

The whole call is guarded once, not per row: it returns `[]` unless the user's
enrollment for `period` has `covers_seminars`. Because the row filter already
pins each event to `period`, that guard *is* `is_tuition_current` for every row
it could return, expressed in one query instead of one per row.

Per row: expire any live Stripe session, set `quoted_amount` to `$0` with
`COVERED_EXPLANATION`, flip `AWAITING_PAYMENT → PAID`, and append an audit line
to `staff_notes`. A `PENDING_APPROVAL` row **keeps its status** — `approve()`
routes on the amount, so flipping it would skip the faculty approval it is
waiting for (the same reasoning `bill_skipped_coverage` already applies). A row
with money actually on it is excluded by the status filter: a fee genuinely paid
is a refund conversation for the treasurer, never a silent unwind, matching
#485.

### Expiring the checkout sessions is load-bearing

At the moment Matt's rows would have gone to `$0`, he had **three live Stripe
checkout sessions worth $1,360** (pay#901/902/903, opened 02:31–02:33 that
morning). Without expiring them, a member who returns to a stale tab pays for a
place they now hold for free — and `complete_payment`'s settle guard mints no
`Charge` against it, so the money lands on their ledger as unattributed credit
for the treasurer to refund by hand.

`stripe_sync.expire_open_sessions(registration, reason=…)` already exists for
exactly this hazard (it was written for cancel-then-re-register) and already
refuses to abandon a session Stripe reports as **paid**, leaving that row PENDING
for the nightly reconcile. Nothing new is needed; it just has to be called.

### Wiring — two paths, deliberately asymmetric

`tuition_decision`'s non-skipping branch calls `apply_coverage` and, when rows
changed, notifies via a new `notify_coverage_restored` (mirror of
`notify_coverage_rebilled`, `ACCOUNT_UPDATES`), built from the rows the function
**returns** — a stale in-memory copy would still read the old amount.

`treasurer_tuition_set_status` calls `apply_coverage` when the new status covers
seminars, and **does not notify** (Rico, 2026-08-11): the treasurer is flipping
historical enrollment years in the #443 cleanup, and a notifying restore would
mail members about registrations they had forgotten.

The treasurer path still does **not** re-bill on skipping. #485's
"staff paths do not auto-bill" rule stands, and it matters more now than when it
was written: flipping historical years during cleanup would retro-bill years of
events. The asymmetry is the intended shape — restoring access is always in the
member's favour and needs no confirmation, while billing is the dangerous
direction and stays behind the member-facing interstitial that shows the cost
first.

## Rejected

- **Keeping `unbill_skipped_coverage` alongside the new function.** Two
  overlapping selectors for one question is how the marker match survived
  unnoticed; the subset relation makes the second one dead weight.
- **Re-pricing lazily at display time** instead of at decision time. It would
  fix the symptom everywhere at once, but `quoted_amount` is what the Pay
  button, the reminders, and `mint_registration_charge` all read — a row that
  displays `$0` while storing `$500` is worse than the bug.
- **Hooking Django admin.** Coverage can only *become* true through the two
  views above plus raw admin editing; the payment paths only move a covering
  status to another covering status (`COMMITTED → PAID_IN_FULL`), and
  `tuition_pay_in_full` bails when no enrollment exists. #485 leaves admin alone
  for the same reason.
- **Notifying on the treasurer path.** See above.

## Consequences

- A member who registers, then records or is given a covering decision, is
  re-priced to `$0` and reads `PAID` — no staff action, no money moving.
- Any live checkout session on a re-priced registration is expired at Stripe and
  settled ABANDONED, so the fee cannot be paid by accident.
- No migration, no backfill, no flag. Matt's four rows were repaired by hand on
  prod on 2026-08-11 with these exact semantics before the code existed.

## Tests

`payments/test_coverage.py`: the #561 scenario (a row quoted at the regular fee
with no marker is restored); the #485 round-trip still restores; a
`PENDING_APPROVAL` row keeps its status; a paid row is untouched; a
pricing-code row is untouched; another academic year is untouched; nothing
happens without a covering enrollment; a live checkout session is expired.
View-level tests cover both wirings and that the treasurer path stays silent.
