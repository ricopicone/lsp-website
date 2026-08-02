# School officers count as workgroup leads (task #480)

**Date:** 2026-08-01
**Task:** #480 — President/VP should count as workgroup leads (video rooms at
minimum, Meeting of Analysts broadly)

## The problem

Verified on prod 2026-07-28 across all 30 workgroups: two have members and zero
owners.

```
Meeting of Analysts        committee        1 member    0 owners
Working Group on Cartels   working_group    6 members   0 owners
```

For the Meeting of Analysts the consequence is that if anyone opens its video
room, *nobody* gets moderator controls (mute / camera-off / remove) and *nobody*
gets a Record button. The room works; it is unmoderatable.

The workgroups layer already treats the school officers as authoritative.
`workgroups/permissions.py::can_manage_workgroup` returns True for the President
and Vice-President on every workgroup, and `Workgroup.participants()` synthesizes
them as leads on the Meeting of Analysts, so they *display* as its leaders. But
the Meeting's leadership is **derived** from synced `StaffRole` holders (the
Board's Chair / Co-chair are the source of truth — see the `board-officer-titles`
memory), never stored as a `WorkgroupMembership` carrying a `LEAD_ROLES` value.

Four call sites re-query the roster directly rather than going through a
predicate, so the derived officers are invisible to them. All four run the same
query:

```python
workgroup.memberships.serving().filter(user=user, role__in=WorkgroupMembership.LEAD_ROLES)
```

| Call site | What it gates |
|---|---|
| `video/services.py::is_owner` | the Daily meeting token's owner flag — moderator controls + Record |
| `video/models.py::Recording._can_host` | who may delete / annotate / keep a recording |
| `parletre/permissions.py::_workgroup_lead` | workgroup-channel moderation |
| `workgroups/permissions.py::workgroup_has_leads` | whether the group is "led" at all |

A fifth, `parletre/permissions.py::channel_can_moderate`'s legacy
committee-access branch, runs the same query keyed by committee rather than
workgroup. It is not in the ticket, but it is the branch that resolves *only* for
committees — which is exactly the Board and the Meeting of Analysts — so leaving
it out would preserve the bug in the one place the fix is aimed at.

That officers already display as MoA leaders is what makes the gap easy to miss:
the roster asserts leadership the permission layer doesn't grant.

## Decisions

### 1. Scope: the Board and the Meeting of Analysts, nothing else

Rico, 2026-08-01. Not the Programming Committee, not other committees, not
cartels, seminars, reading groups or working groups.

The two existing rules are already inconsistent — `can_manage_workgroup` grants
the officers authority over every workgroup, `participants()` synthesizes them
for the Meeting only — and this task reconciles them by adding a third rule that
is narrower than both, applied to the lead question specifically. Management
authority (roster, settings, archive) and *leadership* of a body are different
claims: the President may fix a cartel's roster without being that cartel's lead.

Narrowness is also what keeps the blast radius at zero elsewhere.
`workgroup_has_leads` feeds `can_register_decision`, where a **leaderless** group
lets any active member record a decision. Had the officers counted as leads
everywhere, every cartel would have become lead-led and ordinary cartel members
would have silently lost the decision register. Under this scoping no cartel,
seminar, reading group or working group changes at all.

### 2. The Meeting of Analysts becomes a led group

`workgroup_has_leads` is derived-aware, so the Meeting stops being treated as
leaderless. Recording a decision in its register narrows from any analyst to the
President / Vice-President plus managers (Board, LSP Staff, Programming
Committee, superuser). That matches how the Meeting decides: the officers record
what the body resolved.

The Board is unaffected — it has stored Chair / Co-chair rows and was already
led.

### 3. The orphan guard stays stored-rows-only

`Workgroup.lead_members()` and `Workgroup._would_orphan()` deliberately do **not**
adopt the new predicate.

They guard roster *mutation*, and the Board's stored Chair is the source of truth
that syncs the President `StaffRole` (`committees/officers.py::sync_school_officers`).
A derived-aware orphan guard would permit removing the Board's last Chair on the
grounds that the President covers it — and removing that Chair is precisely what
un-syncs the President. The guard would authorize the change that invalidates its
own premise. Stored rows are the right basis for a question about stored rows.

For the Meeting of Analysts the point is moot: its officers hold no stored rows,
so the roster UI cannot remove them anyway.

### 4. No superuser bypass in the predicate

`is_workgroup_lead` answers "does this user lead this group", not "may this user
do the thing". `core.access.has_staff_role` is explicit-holders-only by design,
and none of the four adopting call sites grant leads to superusers today
(`Recording._can_host` has its own separate `is_staff` clause, which stays).
Adding a bypass here would widen three surfaces as a side effect of a naming
change.

## Design

### The helper

In `workgroups/permissions.py`:

```python
OFFICER_LED_COMMITTEE_SLUGS = ("board", "meeting-of-analysts")

def officer_lead_titles(workgroup) -> dict:
    """{user_id: "President" | "Vice President"} for the school officers who
    lead this workgroup. {} for every workgroup outside
    OFFICER_LED_COMMITTEE_SLUGS."""

def is_workgroup_lead(user, workgroup) -> bool:
    """Whether user leads workgroup: a serving LEAD_ROLES membership, or a
    school officer of a body the officers lead."""
```

`officer_lead_titles` returns `{}` immediately when the workgroup has no attached
committee (`Workgroup.committee` raises `ObjectDoesNotExist`) or its slug is
outside the tuple, so every other workgroup pays one lookup and no user query.

The tuple is a module constant rather than a field on `Committee`. Which bodies
the school officers lead is a governance fact about two named committees, not a
per-committee setting anyone should be able to flip in the admin — and a field
would mean a migration plus a branch to test both ways for something that has one
correct value.

### Adopting call sites

Five, all replacing the raw query:

1. `video/services.py::is_owner` — the Daily token's owner flag.
2. `video/models.py::Recording._can_host` — recording host rights.
3. `parletre/permissions.py::_workgroup_lead` — workgroup-channel moderation.
4. `parletre/permissions.py::channel_can_moderate`, legacy committee branch —
   resolve the committee's workgroup, then the same predicate.
5. `workgroups/permissions.py::workgroup_has_leads`.

### Display

`Workgroup.participants()` drops its inline Meeting-of-Analysts block in favour of
`officer_lead_titles`, and **upgrades** an existing entry rather than replacing
it: an officer who already has a stored membership keeps `membership=`, gaining
only `is_lead=True` and `officer_title`. Today's code overwrites the entry
outright, which is why the block had to be restricted to the auto-membership
Meeting — on the Board it would have discarded the Chair's stored row. With the
upgrade the same code is safe for both, and the Board's rendered roster is
unchanged (its officers are already stored Chair / Co-chair, already relabelled
President / Vice President by `OFFICER_TITLES`).

`workgroups/membership.py::my_groups` gets the same upgrade, so an officer's
Meeting-of-Analysts card on My Groups reads "President" and carries the lead
badge instead of reading "Member".

### What changes in behavior

Meeting of Analysts only:

| Surface | Before | After |
|---|---|---|
| Video room | unmoderatable, no Record button | President / VP moderate and record |
| Recordings | no host | President / VP delete / annotate / keep |
| Parlêtre channel | unmoderated | President / VP moderate |
| Decision register | any analyst records | officers + managers record |

Board: no change. Every other workgroup: no change.

Parlêtre channel moderation is a side effect of the shared predicate rather than
part of the ask, and it is consistent with that module's stated rule — a
workgroup channel is moderated only from within the group, no staff bypass. The
officers are within both bodies (the President is a Board Chair and, as an
analyst, a member of the Meeting).

## Out of scope: Working Group on Cartels

The other zero-owner group is `kind=working_group`, which decision 1 excludes
from the code change. It has 6 members and no organizer assigned; appointing one
in the group's Settings roster fixes it with no code. Confirm on prod that no
organizer is set before making the change — the fix is data, and this spec does
not cover it.

## Testing

- `is_workgroup_lead`: President true for the Meeting of Analysts and the Board;
  false for a cartel, a seminar and the Programming Committee; a plain analyst
  false for the Meeting; a stored chair true.
- `officer_lead_titles`: `{}` for a workgroup with no committee.
- `video.services.is_owner(moa_workgroup, president)` True;
  `is_owner(cartel_workgroup, president)` False.
- `Recording._can_host` for a recording on the Meeting's room.
- `parletre.permissions.channel_can_moderate` on the Meeting's workgroup channel
  and on the legacy committee-access path.
- `workgroup_has_leads(moa)` True; `can_register_decision(moa, plain_analyst)`
  False and `(moa, president)` True.
- The existing leaderless-cartel tests (`workgroups/tests.py`) stay green — they
  are the regression guard for decision 1.
- `participants()` on the Board still returns its Chair with `membership` set
  (the upgrade-not-overwrite guarantee).

## Verification on prod

After deploy, over SSM: iterate `Workgroup.objects.all()`, take
`wg.active_members()` (these are `Participant` wrappers — pass `.user`, not the
participant, or `is_owner` raises `ValueError: Must be "User" instance`) and count
how many satisfy `video.services.is_owner(wg, user)`. Any group with members and
zero owners is a failure. Expect exactly one remaining: Working Group on Cartels,
pending its data fix.

## No migration

No model changes, no data changes, no flag. The scoping is a module constant;
reverting is a revert.
