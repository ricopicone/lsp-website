# Applications Coordinator directory badge (task #481)

## Problem

The Applications Coordinator has no badge in the Directory. Every other named
coordinator does—Referral Coordinator, Cartel Coordinator, Web Coordinator, Web
Developer, Administrative Assistant to the Board all render today.

Two design decisions intersect to produce the gap:

1. The role was deliberately retired as a `core.StaffRole`
   (`core/migrations/0011_retire_applications_coordinator_staffrole.py`, task
   #272) in favour of an officer role on the Meeting of Analysts workgroup,
   `workgroups.WorkgroupMembership.Role.APPLICATIONS_COORDINATOR`. The comment at
   `core/models.py:85-87` records this. So the StaffRole badge path cannot see it.
2. `accounts.views._directory_qs()` prefetches committee memberships filtered on
   `workgroup__committee__public=True` (`accounts/views.py:74`). The Meeting of
   Analysts is seeded `public=False`
   (`committees/migrations/0008_seed_meeting_of_analysts.py:34`). So the committee
   badge path cannot see it either.

The holder therefore falls through both paths and is badged by neither.

## What `Committee.public` actually means

Worth stating precisely, because the field's name invites over-reading. It gates
exactly three things:

- `committees/models.py:67` — the backing workgroup's `landing_visibility`,
  `"public"` vs `"members"`.
- `accounts/views.py:74` — whether memberships badge the public directory.
- `core/templates/core/staff/admin/board_committees.html:33` — a **Public** vs
  **Internal** chip in the Board's committees admin.

That is the whole of it, and it matches the help_text: "Whether this committee has
a public page." The flag makes no claim about confidentiality. **"Internal" is the
app's own word for `public=False`; this spec uses it rather than "private."**

### Why the Meeting of Analysts is Internal

Two independent reasons, worth separating:

- **Internal is the unchanged default.** All four committees were seeded
  `public=False`. Board and Programming Committee were flipped to `True` by
  `committees/management/commands/seed_committees.py:98-100`, which force-opts-in
  every committee it carries a roster for. The Meeting of Analysts is not in that
  command's rosters, so nothing ever flipped it. There was no deliberate "the
  Meeting of Analysts is private" decision to honour or overturn.
- **It should nonetheless stay Internal.** Meeting-of-Analysts membership is not
  an appointment. `committees/migrations/0009_meeting_of_analysts_auto_member.py`
  sets the workgroup's `auto_member_role="analyst"`, so every active Analyst is
  derived into the roster with no stored rows. Flipping the committee to public
  would stamp "Meeting of Analysts" onto every analyst in the directory, directly
  beside the "Analyst" role badge that already conveys it.

## The organising principle

The useful distinction is not public vs. Internal committee. It is:

> **Badge appointed positions. Never badge derived membership.**

On the Meeting of Analysts, *being a member* is a consequence of holding the
Analyst role; *being Applications Coordinator* is an appointment, and the holder
is the named contact in every applicant-facing email
(`admissions/emails.py`—`{applications_coordinator}` is a template variable in six
coordinator messages). The appointment is public-facing whether or not the body
publishes a charter page.

This makes the `role != "member"` exclusion the load-bearing rule rather than an
implementation detail: it is what keeps the Meeting of Analysts' derived analyst
members unbadged while badging its coordinator.

## Rejected alternatives

- **Flip the Meeting of Analysts to `public=True`.** One line, and wrong: it
  publishes a members-only landing page and, because the roster is derived, badges
  every analyst with a committee name that duplicates their role badge.
- **Restore the Applications Coordinator StaffRole, synced from the Meeting of
  Analysts roster** (the President / Vice-President precedent in
  `committees/officers.py`). The badge would come free, but `StaffRole.holders` is
  a permission-granting surface that `core/staff.py` gates on, so a synced row
  would sit beside `workgroups.permissions.is_applications_coordinator` as a
  second, near-miss authorisation path. That is real drift risk for a cosmetic
  gain, and it reverses a deliberate, documented decision from task #272.
- **An allowlist of one publicly-badged officer role.** Considered and declined in
  favour of badging all officer roles: an officer of a school committee holds a
  named appointment, and singling out one role would leave the next appointed
  coordinator with the same bug.

## Design

Confined to `accounts/views.py` and the two directory templates. No model change,
no migration, no new StaffRole. The Meeting of Analysts workgroup roster remains
the single source of truth for who holds the role.

### 1. Prefetch Internal-committee officer memberships

In `_directory_qs()`, add a second membership prefetch alongside
`active_public_memberships`:

- serving memberships (`WorkgroupMembership.objects.serving()`)
- on `workgroup__kind=Workgroup.Kind.COMMITTEE` — this restriction matters:
  `role != "member"` on a cartel or seminar workgroup would otherwise badge
  "Plus-one", "Faculty" and "Organizer"
- whose `workgroup__committee__public=False`
- excluding `role=WorkgroupMembership.Role.MEMBER`
- to `to_attr="badge_officer_memberships"`

Public committees are untouched and keep their richer, primary-coloured
"Committee · Role" badge through the existing prefetch.

### 2. `_badge_officer_roles(user)`

A new helper mirroring `_badge_staff_roles`, returning the officer memberships to
render, minus any whose position is already shown by a StaffRole badge.

Dedup runs one direction—the Internal-committee officer badge is dropped when a
StaffRole covers the same position—because `StaffRole.name` is admin-editable
("Administrative Assistant to the Board") and is the better label wherever both
exist. Position identity is the shared key string: StaffRole keys and
`WorkgroupMembership.Role` values coincide for the overlapping positions
(`treasurer`, `web_coordinator`, `referral_coordinator`, `admin_assistant`), so a
key match is a position match—the same assumption `_badge_staff_roles` already
documents.

Carry over that helper's `chair -> president` / `co_chair -> vice_president`
mapping so a stored Internal-committee chair cannot duplicate the synced President
badge. In practice the Meeting of Analysts cannot trip this—its President /
Vice-President rows are *derived* `Participant`s carrying an `officer_title`
(`workgroups/models.py:463-489`), not stored memberships, so they never appear in
a stored-membership prefetch—but a future Internal committee could store a chair.

Set `profile.badge_officer_roles` in both views that already set
`badge_staff_roles`: `directory()` (`accounts/views.py:270`) and
`directory_detail()` (`accounts/views.py:289`).

### 3. Templates

`directory.html` and `directory_detail.html` render the new list as standalone
**secondary** badges showing `role_label` only—visually identical to the existing
coordinator badges, and silent about the Meeting of Analysts. Secondary is the
correct bucket per the `directory-badge-colors` convention: an operational
coordinator position, not a committee membership.

`role_label` resolves to "Applications Coordinator" here:
`workgroups.OFFICER_TITLES` relabels only the `board` committee, so everything
else falls through to `get_role_display()`.

The card template's `{% if p.is_faculty or mems or roles %}` wrapper and its
`{% with %}` binding must both learn the new list, or the badge row will not open
for a member whose only badge is an Internal-committee officer role.

## Testing

- The Applications Coordinator on the Meeting of Analysts gets an "Applications
  Coordinator" badge on both the directory card and the detail page.
- A plain Meeting-of-Analysts member (the derived-membership case) gets no
  committee badge—the principle above, asserted directly.
- An Internal-committee officer whose position is also a StaffRole they hold gets
  exactly one badge, the StaffRole's editable name.
- An officer role on a non-committee workgroup (cartel/seminar) is never badged.
- Existing assertions keep passing: public-committee officer badges unchanged, and
  `StaffRole.LSP_STAFF` / `REGISTRAR` still unbadged
  (`accounts/tests.py:206-265`).

## Known consequence

`Committee.public` defaults to `False`, so a committee created in the admin later
will badge its officers publicly with no opt-in step. Today this is inert—the
Meeting of Analysts is the only Internal committee, Board and Programming
Committee are both public (verified against the live directory on 2026-07-29), and
the `lsp-staff` committee row was deleted by
`committees/migrations/0006_foldin_committees.py`. But it does mean "Internal
committee" no longer implies "unbadged officers". Recorded here as a property of
the design rather than a surprise.

Separately worth a decision some other time, and independent of this change:
whether the Meeting of Analysts is Internal *on purpose*. This badge behaves
correctly either way.
