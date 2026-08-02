# Registration Admin — a guide

The Registration Admin is the cross-event view of registrations: one place to
see who has registered for what, act on registrations that need a decision,
and open or close registration for each event. It complements the per-event
faculty tools (each event page's roster and approval buttons) rather than
replacing them.

## Who has access

- **Registrar** — a staff role created ahead of the position; when the school
  appoints a Registrar, they are added to the role in the site admin and this
  console is theirs. The role is internal: holders are not listed or badged
  publicly.
- **Web Coordinator.**
- **Program Committee** — every serving member, automatically.
- **Site staff** (Django staff accounts and superusers).

## The Registrations tab

Every registration across every event, newest first. Filter by event, status,
or date range; search by member name or email. The **Active** status filter
(the default) shows registrations that are pending approval, awaiting payment,
paid, or comped; switch to **All** to include declined, cancelled, and
refunded rows.

The **Needs attention** strip at the top lists registrations waiting on an
approval decision, wherever they are in the list.

**Export CSV** downloads the rows matching the current filters.

### Row actions

Each row ends with action buttons for what applies to its status (hover for
labels). Every action records a dated line in the registration's staff notes,
so the override trail stays auditable (REG-14); the sticky-note button shows
existing notes and adds new ones.

- **Approve** (pending approval only) — runs the normal approval: the member
  is emailed, and the registration moves to *awaiting payment* (or straight
  to *paid* when nothing is owed).
- **Decline** (pending approval only) — optionally with a reason, which is
  included in the email to the member.
- **Comp** (awaiting payment only) — waives the fee entirely: the
  registration is confirmed with full access, the member receives the
  confirmation email, and the waived amount still appears on their ledger
  statement.
- **Add note** — appends a staff note without changing anything else.

## The Events tab

One row per event in the current and upcoming academic year, with
registration counts by status and an **Open registration / Close
registration** button.

Opening registration is what lets members register (and pay); closing it
stops new registrations. This is separate from *publishing* the event page,
which controls public visibility and is managed in the Program Committee
admin. Closing never cancels existing registrations.

## What lives elsewhere

- **Recording an offline payment** (cash, check, alternate arrangement):
  Treasurer Admin, or the Payment admin's "Apply payment success" action.
- **Refunds and cancellations**: the member's own confirmation page
  (self-service Stripe refund) or the Treasurer Admin.
- **Adjusting a quoted amount**: the Django admin, per the manual-override
  workflow (REG-14).
- **Pricing codes**: minted by faculty from their event page's faculty view.
