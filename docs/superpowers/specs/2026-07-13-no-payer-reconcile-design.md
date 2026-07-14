# "No payer" attribution queue (treasurer Reconcile tab)

**Date:** 2026-07-13
**Context:** The audit found 63 Stripe-imported charges (~$15,650) that are
confidently *typed* but linked to **no member** and carry `source=stripe`. The
existing Reconcile queue only surfaces `source=ASSUMED` rows, so these fall
through the cracks — they count in totals but never appear in any per-member
view and can't be attributed from the UI.

## Goal

Give the treasurer a place to resolve every unattributed Stripe charge: link it
to a member, keep it as a named non-member payer, or mark it an anonymous
donation — each with a category.

## Queue definition

`Payment.objects.filter(source=Source.STRIPE, user__isnull=True)`. This is
disjoint from the Reconcile queue (`source=ASSUMED`), so the two never overlap.
A charge leaves the queue when it is resolved (below).

## Placement & UI

A **second section on the existing Reconcile tab** (`reconcile.html`), below the
current provisional-type section, headed "No payer — confidently typed, needs a
payer." Charges are **grouped by payer name** (parsed from the
`(unmatched payer: …)` note), reusing the same grouping the Reconcile section
already uses. Each group shows its charges (count, total, dates, current type)
and one resolution form:

- **Category** — a `payment_type` `<select>`, defaulted to the group's current type.
- **Link to member** — the same `Name (email)` autocomplete (`<datalist>`) the
  Reconcile section uses (`_reconcile_member_options` / `_resolve_assign_user`).
- **Payer name** — a text field pre-filled from the parsed note name, used when
  *not* linking to a member.
- Buttons: **Save** (applies category + member-or-name) and **Anonymous
  donation** (one-click, no confirm — sets type=donation, no payer).

## Resolution semantics (`_no_payer_apply`)

POST to `treasurer_reconcile` with a hidden `form=no_payer` (the existing
Reconcile POST becomes `form=reconcile`). Constrained to the queue
(`source=STRIPE, user__isnull=True, pk__in=ids`) so a stale/forged id can't
touch a confirmed row. Every resolution sets `source=Source.VERIFIED` — the same
promotion the Stripe reconcile path already applies to confirmed rows — which is
what removes the charge from the queue.

- **action=anonymous:** `payment_type=DONATION`, user stays null, `source=VERIFIED`.
- **action=save + assign_user given:** resolve to a `User`; set `user`,
  `payment_type`, `source=VERIFIED`.
- **action=save + no assign, payer_name given:** keep user null; set
  `payment_type`, `source=VERIFIED`; rewrite the `(unmatched payer: …)` note
  segment to the (possibly edited) name (or append `payer: <name>` if absent).
- Invalid type or unresolvable member → `messages.error`, redirect, no change.
- Success → `messages.success` with a count, redirect back to Reconcile.

Assigning to a member also leaves the queue naturally (user no longer null).

## Reuse / refactor

Factor the payer-grouping block out of `treasurer_reconcile` into a helper
`_payer_groups(payments, *, matched_default)` and call it for both the Reconcile
(ASSUMED) and No-payer (STRIPE/null) sections. Reuse `_payer_name_from_notes`,
`_reconcile_member_options`, `_resolve_assign_user` unchanged.

## Out of scope (YAGNI)

- No new model fields / migration — reuses `user`, `payment_type`, `source`, `notes`.
- No bulk "assign everything" across groups; per-group only.
- No auto-matching by fuzzy name (a later `manage.py` job could attempt it).

## Testing

- Queue lists `source=stripe, user=None`; excludes assumed and member-linked rows.
- Assign-to-member: links user, sets type, source=verified, drops from queue.
- Anonymous donation: type=donation, user stays null, source=verified.
- Named payer: type set, user null, note carries the name, source=verified.
- Constrained: a posted id outside the queue is untouched.
- The Reconcile (ASSUMED) section still works (regression).
