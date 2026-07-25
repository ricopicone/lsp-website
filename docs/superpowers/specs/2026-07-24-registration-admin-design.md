# Registration Admin console — design

**Date:** 2026-07-24 · **Task:** #470 · **Status:** approved

## Problem

There is no cross-event view of registrations. Staff who need to see or act on
registrations today bounce between per-event faculty views (approve/decline,
roster), the Django admin (comp action, notes), and the treasurer surface
(payment rows). The school has no Registrar position yet, but one is likely;
until then the Programming Committee and the Web Coordinator are the natural
operators.

## Decision summary

A **standalone console** at `/admin-tools/registrations/` (not a PC-admin tab —
the PC already has a full plate, and this surface is expected to grow into a
distinct role's home). A new **`registrar` StaffRole** is created now,
unheld, so appointing a future Registrar is a data change, not a code change.
Registrar holders are **never publicly badged**.

## Access

One decorator (`registrar_required`) admits, in order of check:

- superuser or `is_staff`
- `registrar` StaffRole holder
- `web_coordinator` StaffRole holder
- serving Programming Committee member (`events.permissions.is_program_committee`,
  a live roster check — no per-member role assignment to manage)

The same predicate gates the admin-tools hub card and joins
`core.staff.can_access_admin_tools`.

### StaffRole.REGISTRAR

- New well-known key `registrar`, name "Registrar", seeded by data migration.
- Added to the directory-badge exclusion in `accounts/views.py` (the
  `_directory_qs` Prefetch that already excludes `LSP_STAFF`), so holders get
  no public badge. The badge-dedupe helper then never sees it.

## Structure

Code lives in the existing `registrations` app: a new `registrations/views_admin.py`,
templates under `registrations/templates/registrations/registrar/`, URLs in
`registrations/urls.py` with an `admin-tools/registrations` prefix (the
`referrals/` console is the pattern: module-level `TABS`, `_tab_links()`,
`_render()`, app-local `base.html` extending `core/base.html` +
`core/_admin_tab_nav.html`).

### Tab 1 — Registrations

Cross-event table: member, event, tier, quoted amount, status, created date.

- Filters: event, status, date range. Search: member name/email. Paginated 50.
- A "Needs attention" strip at the top surfaces `pending_approval` rows.
- **Export CSV** honoring the current filters.
- Row actions (inline): **approve**, **decline** (with reason), **comp**,
  **add note**. Every action writes the standard dated `staff_notes` audit
  line and fires the same notifications the existing paths fire.

### Tab 2 — Events

One row per event (current + upcoming academic year): status
(Draft/Open/Closed), registration counts by status, links to the event page /
roster, and an **Open registration / Close registration** toggle.

*Amended during planning:* `Event.status` DRAFT means "registration not yet
open" — it is distinct from the `Event.published` visibility flag, and the
existing PC bulk view (`program_admin_registration_bulk`) already flips
DRAFT→OPEN. The console toggle follows the same convention: **open =
DRAFT/CLOSED → OPEN; close = OPEN → CLOSED.** Publishing (`published`)
remains a decision made elsewhere.

### Tab 3 — Help

`core/docs/registrar-guide.md`, rendered via `core.docs.render_doc` like the
other console guides, and registered in the hub Documentation section.

## Action plumbing — reuse, not duplicate

- **Approve / decline** call the existing `Registration.approve(by)` /
  `.decline(by, reason)` model methods (which already send notifications).
- **Comp**: the body of the Django-admin `comp_selected_registrations` action
  is extracted into a shared `registrations/services.py::comp_registration()`
  used by both the admin action and the console, so the side-effect chain
  (status flip, `staff_notes` line, `mint_comped_charge`,
  `registration_confirmed` notification) cannot drift. Only
  `AWAITING_PAYMENT` rows are compable, as today.
- **Add note** appends a dated line to `staff_notes`.
- **Open/close registration** flips `Event.status` with a Django-messages
  confirmation. No audit field exists on Event for this; the flip is visible
  in the console and reversible, so no new audit machinery is added.

## Out of scope (deliberate)

- Offline-payment recording (treasurer surface owns it).
- Quoted-amount editing (rare, payment-coupled — Django admin stays the
  REG-14 escape hatch).
- Cancel/refund (member self-service + treasurer/Django admin).
- Pricing-code minting (faculty per-event interface owns it).

## Testing

pytest-django coverage for:

- Gate: each admitting principal (superuser, `is_staff`, registrar holder,
  web_coordinator holder, serving PC member) passes; a plain member is denied
  (404 per console convention).
- Actions: approve/decline/comp/note each produce the right status flip,
  `staff_notes` line, notification, and (comp) minted charge; comp refuses
  non-`AWAITING_PAYMENT` rows.
- Registrations tab: filters, search, pagination, CSV columns + filter
  honoring.
- Events tab: open flips DRAFT/CLOSED→OPEN; close flips only OPEN→CLOSED
  (a close on a DRAFT event is a no-op).
- Directory: a registrar holder shows no registrar badge.
