# Anonymous donations pathway (task #414)

## Problem

The "Payments" nav tab is gated behind `{% if user.is_authenticated %}`, and
`payments_index` (`/payments/`) is `@login_required`. Logged-out visitors who
want to make a gift have no obvious way in, even though the donation flow itself
already supports anonymous gifts. The School wants a public payments entry point
that branches: sign in to manage your own payments, or donate anonymously.

## Goal

Expose the "Payments" tab to everyone and give logged-out visitors a branching
gateway at `/payments/` — **sign in** to manage payments, or **donate
anonymously**. On the donate page, encourage (but never require) sign-in so
donations can be tracked, while still allowing a fully anonymous gift.

No data-model or migration work: the `donate` view and the `Payment.user=None`
path already support anonymous donations.

## Changes

### 1. Navigation — `core/templates/core/base.html`

Remove the `{% if user.is_authenticated %}` guard around the "Payments" link in
both places:

- Desktop nav (~line 156–158).
- Mobile hamburger menu (~line 206–209) — the surrounding `<hr>` divider stays
  sensible for anonymous users.

The `/payments/`, `/dues/`, `/donate/` active-state highlight is unchanged.

### 2. `payments_index` view — `payments/views.py`

Drop `@login_required`. Branch on `request.user.is_authenticated`:

- **Authenticated** → render the existing `payments/index.html` with the current
  context (what's due, activity cards, personal payment history) — unchanged.
- **Anonymous** → render a new `payments/gateway.html`. The view builds no
  member context for this branch, so no per-user data is touched.

### 3. Gateway template — `payments/templates/payments/gateway.html` (new)

A short intro and two cards:

- **"Sign in to manage your payments"** → `{% url 'login' %}?next={% url 'payments:index' %}`.
  After sign-in the visitor lands back on `/payments/`, which now renders the
  member page.
- **"Donate to LSP"** → `{% url 'donate' %}`; copy makes clear no account is
  needed.

Uses the same page-hero / section styling as `index.html` and DaisyUI semantic
tokens only.

### 4. Donate page nudge — `payments/templates/payments/donate.html`

For anonymous users only (`{% if not user.is_authenticated %}`), add an info
banner above the form: *"Have an LSP account? Sign in to track your donations and
receipts."* with a sign-in link (`{% url 'login' %}?next={% url 'donate' %}`).
The form still submits anonymously; the banner is pure encouragement.

## Conventions

- DaisyUI semantic tokens only (`bg-base-100`, `text-base-content`,
  `text-primary`, …) — no hardcoded colors.
- Member-facing copy uses commas, not em dashes (`em-dash-prose-style`
  exception for site copy).
- This is a deliberate **non-redirect** for anonymous users. The shared
  `core.access.gate_or_login` helper redirects anon users to login; that is the
  opposite of what we want here, so it is intentionally not used.

## Testing

- `payments_index`: anonymous GET returns **200** and renders `gateway.html`
  (asserts it is *not* a login redirect); authenticated GET still renders the
  member `index.html`.
- Smoke check: the donate flow still works logged-out (GET `/donate/` 200 for an
  anonymous user; the existing anonymous-donation POST path is unchanged).

## Out of scope

- No changes to the `donate` POST handler, `Payment` model, Stripe session
  creation, receipts, or the `payment_thanks` page.
- No new "track my anonymous donations" reconciliation (donations made while
  logged out stay attached by `email` only, exactly as today).
