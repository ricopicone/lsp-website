# Member Payments hub — design

**Date:** 2026-07-06
**Task:** #354 (Add a Payments tab). Companion: #355 (payment due dates on the calendar) — separate.
**Source:** Annie Rogers / Diana Cuello / Garrett website-review meeting (task #345).
**Status:** proposal — Rico reviews with Garrett before/around implementation.

## Motivation

Member payment actions are scattered: `/dues/`, `/donate/`, the My-LSP hub's
Tuition tab (`/formation/?tab=tuition`), and receipts that only arrive by email.
There is no single place a member can go for "anything to do with paying LSP."
This adds one — a central **Payments page** that **links out** to the existing,
unchanged flows (we are *not* merging the Tuition and Dues surfaces; they stay as
their own rationalized pages) and adds the one missing surface: the member's own
payment history + downloadable receipts.

## Scope

- **New:** a login-required member Payments index at `/payments/` with a
  "what's due" summary, link-cards to Dues / Tuition / Donate, and an inline
  payment-history + receipts section.
- **New:** an owner-gated member receipt view/download (today only the treasurer
  can resend a receipt by email; members have no way to view/download their own).
- **Nav:** a "Payments" entry in the signed-in **account/avatar dropdown**, with
  the existing "Donate to LSP" item grouped under it.
- **Unchanged:** `/dues/`, `/donate/`, the Tuition tab, checkout flows, the
  `Payment`/`Receipt` models, the treasurer surfaces. This page composes and
  links; it does not reimplement them.

## Location & routing

- `payments/urls.py` currently has only `webhooks/`, `transactions.csv`,
  `<id>/thanks/`. Add:
  - `path("", views.payments_index, name="index")` → `/payments/` (login required).
  - `path("<int:payment_id>/receipt/", views.receipt_download, name="receipt")`
    → owner-gated receipt (the member who owns the payment, or staff).
- Mounted under the existing `/payments/` include in `config/urls.py`.

## The page (`payments/templates/payments/index.html`)

Signed-in member only. Sections, top to bottom:

1. **What's due** — shown only when the member has an outstanding obligation:
   unpaid dues for the current `DuesPeriod` (role-tiered amount + due date) and/or
   a due tuition installment. Each row: label, amount, due date, **Pay** button
   (links to the existing dues/tuition checkout). If nothing is owed, this block
   is omitted (or a quiet "You're all paid up.").
2. **Dues** card → links to `{% url 'dues' %}`, one-line status teaser
   (paid this period / amount owed / not obligated), reusing
   `payments.dues.is_dues_obligated` + `DuesPeriod.amount_for_role`.
3. **Tuition** card → links to `{% url 'formation:formation' %}?tab=tuition`,
   one-line current-AY status teaser (committed / plan / paid in full / skipping /
   no decision), reusing the existing tuition status helper.
4. **Donate** card → links to `{% url 'donate' %}`.
5. **Payment history & receipts** (inline, new) — a table of the member's own
   `Payment`s (date · type · amount · status), newest first; each paid row with a
   `Receipt` shows a **Download receipt** link to `payments:receipt`.

Copy uses commas, not em dashes (task #352). DaisyUI semantic tokens only.

## Backend

- **`payments_index(request)`** (login_required): assembles the member's
  obligations (reuse dues/tuition helpers) + their payment history
  (`Payment.objects.filter(<member>)`, newest first, `select_related("receipt")`).
  Resolve the member linkage from the `Payment`→user FK; where a payment is keyed
  only by `email`, match the member's addresses. (Plan verifies the exact
  `Payment` member field.)
- **`receipt_download(request, payment_id)`** (login_required): 404 if the payment
  isn't the requester's own (and they aren't staff); otherwise render/serve the
  `Receipt`. Reuse whatever the receipt template/PDF path already is; if receipts
  are HTML-only today, render the existing receipt template gated to the owner.
- No new models. No changes to checkout, webhook, or receipt-generation logic.

## Nav wiring

In `core/templates/core/base.html` account/avatar dropdown: add a **Payments**
link (`payments:index`) and group the existing **Donate to LSP** under it (e.g.
Payments, then Donate indented/adjacent). Members only (login-gated menu region).

## Permissions & empty states

- Whole page is login-required; a member sees only their own obligations,
  history, and receipts.
- Each section degrades gracefully: no dues obligation, no tuition decision, and
  empty payment history all render calm empty states rather than errors.

## Testing

- `/payments/` renders 200 for a signed-in member; 302→login for anonymous.
- "What's due" reflects a seeded unpaid dues obligation; absent when paid.
- Dues/Tuition/Donate cards link to the correct URLs.
- Payment history lists only the requesting member's payments, newest first.
- `receipt_download`: owner gets the receipt; a different member gets 404; staff
  allowed.
- Avatar dropdown shows Payments (with Donate grouped) for a signed-in member.

## Open questions for Garrett (flag in review)

- Should members see their **full** payment history and self-download receipts?
  (Assumed yes.)
- Any dues/tuition amounts, due-date logic, or wording he wants reflected in the
  "what's due" summary.
- Whether donations should also appear in the member's payment history (assumed
  yes, since a `Payment` row exists for them).

## Out of scope

- #355 (due dates → global calendar) — separate task.
- Any change to the Tuition or Dues pages themselves (explicitly *not* merged).
- Treasurer-side changes.
