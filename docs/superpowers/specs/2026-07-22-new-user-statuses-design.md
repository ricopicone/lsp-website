# New User Statuses — Design (task #451)

**Date:** 2026-07-22
**Status:** Approved, ready for implementation plan
**Branch:** silver-quartz

## Problem

The school needs three additional member states that the current model can't
express cleanly:

- **Removed** — treated as a *non-member* account. Can be reinstated. Role
  (e.g. Candidate Analyst) and history are retained. Must not appear in the
  directory, and should not be counted in most admin dashboards.
- **Retired** — still treated as a *member*. Applies to Analysts and Scholars
  (not in-training members). Still appears in the directory.
- **Deceased** — the account must not work (security). Still appears in the
  directory. Not expected to pay.

## Existing architecture this builds on

The codebase already has a **membership-lifecycle axis** that is the right home
for most of this — `Profile.Standing` (orthogonal to `Profile.role`):

```python
# accounts/models.py:92-99
class Standing(models.TextChoices):
    ACTIVE = "active", _("Active")
    ON_LEAVE = "on_leave", _("On leave")
    RESIGNED = "resigned", _("Resigned")
    EMERITUS = "emeritus", _("Emeritus")
```

Key facts discovered during design:

- The Board sets standing through a single chokepoint,
  `accounts/membership.py:record_membership_change(...)`, which keeps the live
  `Profile.standing` cache and the historical `MembershipTenure` timeline in
  sync. New standing values flow through `MembershipChangeForm`
  (`accounts/forms.py:360`) and the Board membership admin
  (`core/staff.py:313`) automatically.
- **Every dues/tuition obligation gate already keys off
  `standing == Standing.ACTIVE`** (`payments/dues.py:19-43`,
  `Profile.owes_tuition` at `accounts/models.py:474-483`). So any new non-active
  standing is *automatically* exempt from billing, charge minting, and dues/
  tuition reminders — no queryset changes needed for the "don't expect payment"
  requirement.
- **Directory** (`accounts/views.py` `_directory_qs` ~line 70, `directory_map_data`
  ~line 349) and the **membership predicate** (`accounts/permissions.py:is_lsp_member`,
  mirrored in `core/templatetags/core_tags.py`) key off `role ∈ DIRECTORY_ROLES`
  (+ `public`) and **do not currently consult `standing` or `is_active`**. These
  must become standing-aware to hide Removed/Resigned.
- **Login**: `User.is_active=False` blocks both password login (Django
  `ModelBackend`/`AuthenticationForm`) and magic-link login (explicit guard at
  `accounts/views.py:734`). There is no custom auth backend and no existing
  automated deactivation flow. This is the mechanism for the Deceased security
  requirement.

## Design decisions

### Deceased is orthogonal, not a standing

Deceased is a fact about the person (with a security consequence), not a
membership decision, and a member can be *both* Retired and Deceased. So it is a
separate field, **not** a `Standing` value:

- `Profile.deceased_on = DateField(null=True, blank=True)`.

Setting it drives `user.is_active=False` and a memorial treatment in the
directory. The member's `standing`/`role` are left intact (history preserved).

### Retired and Removed are new Standing values

`Profile.Standing` gains two values (Emeritus is kept — it is a distinct,
Board-conferred honorific):

```python
    RETIRED = "retired", _("Retired")
    REMOVED = "removed", _("Removed")
```

Mirror the same choices into `MembershipTenure.standing`.

### Which standings strip membership + directory

A new set marks the standings that are **not** members and drop off the
directory. Resigned joins Removed here (a resigned member has left):

```python
    NON_MEMBER_STANDINGS = frozenset({Standing.RESIGNED, Standing.REMOVED})
```

Everything else (active, on_leave, emeritus, retired) keeps member access and
directory listing as today.

### Behavior matrix

| State | Login | Members-only | Directory | Billed | Referral pool | Member dashboards |
|---|---|---|---|---|---|---|
| active | ✓ | ✓ | ✓ (if `public`) | ✓ | ✓ | counted |
| on_leave | ✓ | ✓ | ✓ | — | unchanged | counted |
| emeritus | ✓ | ✓ | ✓ | — | unchanged | counted |
| **retired** (new) | ✓ | ✓ | ✓ | — | **excluded** | counted |
| **resigned** (changed) | ✓ | **✗** | **✗** | — | **excluded** | **not counted** |
| **removed** (new) | ✓ | **✗** | **✗** | — | **excluded** | **not counted** |
| **deceased_on set** (orthogonal) | **✗** | n/a¹ | ✓ **+ "In memoriam"** | — | **excluded** | not counted² |

¹ A deceased account can't log in, so the members-only path is never reached.
² Deceased are excluded from *member* dashboards; the treasurer's
`accounts_overview` still lists anyone with ledger history (unchanged), but
auto-waive (below) means they show no false "owing".

## Changes by area

### Data model — `accounts/models.py`
- Add `RETIRED`, `REMOVED` to `Standing`; mirror into `MembershipTenure.standing`.
- Add `deceased_on` DateField.
- Add `NON_MEMBER_STANDINGS` frozenset and a convenience predicate, e.g.
  `Profile.is_active_member` (member iff `standing ∉ NON_MEMBER_STANDINGS` and
  not deceased) and `Profile.is_deceased`.
- `Profile.save()` (or the transition handler) syncs `user.is_active` from
  `deceased_on`: set inactive when a date is present, re-enable when cleared.
  Guard so this only toggles as a function of `deceased_on` (no other
  deactivation flow exists today).
- Migration: one schema migration (new `deceased_on` column; the enum additions
  are choices-only). No data migration — no existing retired/removed/deceased rows.

### Membership predicate & directory
- `accounts/permissions.py:is_lsp_member` and the duplicate in
  `core/templatetags/core_tags.py` → exclude `NON_MEMBER_STANDINGS`.
- `accounts/views.py` `_directory_qs` and `directory_map_data` → exclude
  `NON_MEMBER_STANDINGS`; **keep** deceased members listed.
- Directory templates → show an unobtrusive "In memoriam" marker on deceased
  members' card + detail page, and suppress referral/contact call-to-action for
  them.

### Referral pool — `referrals`
- On transition to retired / resigned / removed / deceased, deactivate the
  member's `ReferralListMember` (`is_active=False`) so they drop out of
  distribution. Reinstatement does **not** auto-reactivate the referral listing
  (member re-opts via the profile editor).

### Dashboards
- `core/staff.py:board_governance` member query and the board-appointments
  appointable list → exclude `NON_MEMBER_STANDINGS` and deceased.
- Treasurer `accounts_overview` (`payments/ledger.py`) → unchanged.

### Financial: auto-waive open charges (decision (a))
When a member is marked Removed or Deceased, dues/tuition **stop minting**
automatically (existing `standing != ACTIVE` gates), but any *already-open*
Charge rows remain. Handling, per the do-not-over-automate principle:

- **Deceased** → **auto-waive** all open charges, writing an audited note
  ("Waived — member deceased"). Clean and non-reversible-in-spirit.
- **Removed** → **do not** auto-waive (Removed is reinstatable; auto-waiving then
  reinstating would silently erase real debt). Instead the Board membership admin
  surfaces the member's open balance with a one-click **"Waive open charges"**
  action (audited note), keeping a human in the loop.

Implementation: a shared helper, e.g. `payments/charges.py:waive_open_charges(
user, *, reason, by)`, that waives/voids open Charge rows with an audit note.
Called automatically for Deceased; exposed as a button for Removed.

### Safety belts (flagged during exploration)
- `payments/charges.py:sync_tuition_charges` today checks `role` but not
  `standing` — add a standing hard-stop so it can't mint for a non-active member.
- `payments/management/commands/send_registration_reminders.py` has no standing/
  is_active filter — add one so Removed/Deceased members with an unpaid
  registration aren't nagged.

### Setting the status (UI)
- **Retired / Removed**: appear automatically in the existing Board membership
  form (`MembershipChangeForm` standing dropdown → `record_membership_change`).
  Reinstate = set standing back to Active. Removed also shows the one-click
  "Waive open charges" action.
- **Deceased**: a dedicated control (a date field) on the Board membership admin
  and the Django admin Profile page. Setting it disables the account +
  auto-waives + deactivates referral listing; clearing it re-enables the account.

## Testing
- Standing/deceased billing exemption (dues + tuition minting and reminders skip
  retired/removed/resigned/deceased).
- Directory: retired/on_leave/emeritus listed; resigned/removed excluded;
  deceased listed with memorial marker and no referral CTA.
- Membership predicate: removed/resigned are non-members; retired is a member.
- Login: deceased account blocked for both password and magic-link; clearing
  `deceased_on` re-enables.
- Auto-waive: deceased auto-waives open charges (audited); removed does **not**
  auto-waive, but the waive action works and is audited.
- Referral pool exclusion on transition.
- Dashboards exclude removed/resigned/deceased.
- Reinstatement round-trip (removed → active restores member access; deceased
  cleared restores login).

## Out of scope
- Revisiting on_leave / emeritus behavior (unchanged).
- Any new role changes (statuses are on the standing/deceased axes, not `role`).
- Bulk/import handling of the new statuses (no importer path requested).
