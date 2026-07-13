# Payment provenance info hover (treasurer tables)

**Date:** 2026-07-13
**Context:** Task #435 follow-up. Reviewing Garret Barnwell's treasurer page,
the Payments table showed rows with `Method = Offline` and a burst of June
transactions with no visible explanation. The explanation already exists in the
data — `Payment.source` (provenance) and `Payment.notes` (import tag +
reconciliation annotations) — but the member-detail and Payments-tab tables
don't surface it. The treasurer can't tell that those "Offline" rows came from
importing the treasurer ledger (`[tz-import:…]`, "method unrecorded in ledger"),
not from a literal cash claim.

## Goal

Surface the provenance we already store, on hover, next to each payment row, so
the treasurer understands where a row came from without opening Django admin.

## What we already have

- `Payment.source` — `accounts.Source` TextChoices with human labels:
  Verified against records / Imported from treasurer ledger / Member-reported
  (survey) / Assumed / Entered by staff. Already surfaced as a badge on the
  tuition and dues tabs via `payments/treasurer/_source_badge.html`.
- `Payment.notes` — staff/import notes. Import rows carry a leading machine tag
  and ` | `-separated annotations, e.g.
  `[tz-import:tuition-24-25#1] | installment: 1st | method unrecorded in ledger`
  or `[stripe-import:ch_3TZx…] (provisional — confirm via …)`.
- `Payment.member_note` — a note the member wrote (today shown only on the
  Payments tab's Type cell).

## Design

### 1. Notes-cleaning filter (pure logic, TDD)

Add to `payments/templatetags/treasurer_filters.py`:

```
@register.filter
def provenance_lines(notes: str) -> list[str]
```

Behaviour:

1. Empty / whitespace → `[]`.
2. Split on ` | `; strip each segment; drop empties.
3. **First segment** — detect a leading bracketed tag
   `^\[([a-z-]+):([^\]]+)\]\s*(.*)$`:
   - group1 = tag kind, group2 = reference, group3 = trailing text.
   - Map tag kind → label: `tz-import` → "Treasurer ledger ref",
     `stripe-import` → "Stripe charge"; fallback
     `kind.replace("-import","").replace("-"," ").title()` + " ref".
   - Line = `"<label> · <reference>"`, with ` <group3>` appended when group3 is
     non-empty (preserves `(provisional — …)`).
   - If the first segment starts with `[` but has no colon (e.g.
     `[assume-skip dues-24-25]`), strip the brackets and show verbatim.
   - If it isn't bracketed at all, show verbatim.
4. **Remaining segments** — verbatim, one line each.
5. Return the list of non-empty lines.

Tests cover: empty, `tz-import` tuition/dues, `stripe-import` with and without a
`(provisional…)` parenthetical, a multi-segment tz row, a bracket-without-colon
tag, and a plain un-tagged staff note. Real strings from Garret's rows are the
fixtures.

### 2. Reusable popover partial

`payments/templates/payments/treasurer/_provenance_popover.html`, params:
`payment` (and it reads `payment.source`, `payment.get_source_display`,
`payment.notes`, `payment.member_note`).

Renders **only when** `payment.notes or payment.member_note` — otherwise emits
nothing (so normal live payments show no affordance). Structure:

- A `group relative inline-flex` wrapper.
- Trigger: an inline-SVG ⓘ icon, `tabindex="0"`,
  `aria-label="Payment source and notes"`.
- Popover card: absolutely positioned, hidden by default, shown on
  `group-hover` and `group-focus-within`
  (`hidden group-hover:block group-focus-within:block`). No JS.
  DaisyUI semantic tokens only (`bg-base-100`, `border-base-300`,
  `text-base-content`, shadow). `w-64`, small text, `z-20`.
  Contents:
  - `{% include "payments/treasurer/_source_badge.html" with source=payment.source label=payment.get_source_display %}`
  - `{% for line in payment.notes|provenance_lines %}` → each as a short
    `text-xs text-base-content/70` line.
  - If `payment.member_note`: a labeled `Member note: “…”` block
    (`text-info/80 italic`).

A thin variant for the badge tabs: the same popover but the **trigger is the
existing source badge** rather than a separate icon. Implement as one partial
that takes a `trigger` param (`"icon"` default, or `"badge"`); the badge tabs
pass `trigger="badge"` and their existing `_source_badge` include moves inside
the wrapper.

### 3. Wiring

- **member_detail.html** Payments table: add a trailing `<th></th>` / `<td>`
  rendering the popover with `trigger="icon"`. (Also gains the member-note
  visibility it lacks today, inside the popover.)
- **payments.html** Payments tab: same trailing ⓘ column with `trigger="icon"`.
  Keep the existing member-note line in the Type cell as-is (harmless
  duplication) or drop it — drop it, since the popover now carries it.
- **tuition.html** + **dues.html**: replace the bare `_source_badge` include in
  the existing source column with the popover partial using `trigger="badge"`,
  so hovering the badge reveals the notes. No new column.

### 4. Accessibility / behaviour

- Keyboard: icon/badge is focusable; popover shows on `focus-within`.
- Mobile: tap focuses the trigger → popover shows; tapping elsewhere blurs.
- No new JS, no new dependencies.

## Out of scope (YAGNI)

- No editing of notes/source from the hover (that stays in Django admin).
- No Stripe-dashboard deep links from the charge id.
- No changes to the import commands or the notes format itself.
- No reconciliation workflow — this only *displays* what we already store.

## Testing

- Unit tests for `provenance_lines` (the fixture cases above).
- A template-render smoke test: member_detail / payments views render with an
  imported payment and the popover markup (source label + a cleaned line)
  appears; a plain payment with no notes renders no popover trigger.
