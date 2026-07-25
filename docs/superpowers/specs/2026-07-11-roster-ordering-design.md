# Roster ordering: leaders first, then alphabetical (task #417)

## Problem

Members on the About page (Board of Directors, Program Committee), on committee /
workgroup group pages, and on every group roster are listed in a strange order.
Today there is **no officer ordering** anywhere: every roster surface funnels
through `Workgroup.active_members()`, which applies no explicit sort and falls
back to the model default `Meta.ordering = ("workgroup__name", "-start_date")` —
so within a group members come out most-recently-added first.

## Goal

Order every group's roster as: **leaders first** (by a fixed role precedence —
president before vice president before secretary, etc.), then **everyone else
alphabetically by last name**. Within any single role, ties break alphabetically
by last name, then first name.

## Role precedence (the rank table)

President / Vice President are **not** stored roles — on the Board the underlying
`WorkgroupMembership.role` values are `chair` / `co_chair`, relabeled to
"President" / "Vice President" for display via `content.views.OFFICER_TITLES`.
The rank table therefore ranks the *stored* roles:

| Rank | `WorkgroupMembership.Role` | Displayed as (Board) |
|---|---|---|
| 1 | `CHAIR` | President |
| 2 | `CO_CHAIR` | Vice President |
| 3 | `SECRETARY` | Secretary |
| 4 | `TREASURER` | Treasurer |
| 5 | `ORGANIZER` | Organizer |
| 6 | `REFERRAL_COORDINATOR` | Referral Coordinator |
| 7 | `APPLICATIONS_COORDINATOR` | Applications Coordinator |
| 8 | `ADMIN_ASSISTANT` | Admin Assistant |
| 50 (default) | everyone else — `MEMBER`, `FACULTY`, `WEB_COORDINATOR`, any future role | Member / etc. |
| 99 | `PLUS_ONE` | Guest |

`MEMBER`, `FACULTY`, and `WEB_COORDINATOR` are deliberately **not** distinct
officer positions (per stakeholder) — they share the "everyone else" default
rank and sort purely alphabetically. Using a default rank (rather than
enumerating every role) means any role added to the enum later automatically
lands in the everyone-else tier instead of ranking 0/undefined.

### Seminars / faculty note

For seminars the instructor carries the `faculty` role, which under this table
sorts into the everyone-else tier rather than at the top. This is acceptable
because seminar rosters are **not displayed anywhere** in the current UI — so no
special-casing for faculty is included. If seminar rosters ever get a display
surface, revisit whether faculty should float above the everyone-else tier.

## Approach (chosen: A)

A role→rank mapping applied at the single query chokepoint, plus a matching
sort of the assembled `participants()` list. **No migration** — this is a pure
ordering rule, not stored data.

Rejected alternatives:
- **B — add a `sort_order` IntegerField** to `WorkgroupMembership` (mirrors
  `events.EventMemberSpeaker`). Enables hand-tuned per-person ordering, but the
  rule here is deterministic, so the field would go unused; needs a migration +
  admin data entry. Overkill.
- **C — sort in each template/view.** Duplicated logic that drifts out of sync
  and misses surfaces.

## Design

All changes in `workgroups/models.py` unless noted.

### 1. Rank map + shared sort key — `WorkgroupMembership`

```python
ROSTER_DEFAULT_RANK = 50

ROLE_RANK = {
    Role.CHAIR: 1,
    Role.CO_CHAIR: 2,
    Role.SECRETARY: 3,
    Role.TREASURER: 4,
    Role.ORGANIZER: 5,
    Role.REFERRAL_COORDINATOR: 6,
    Role.APPLICATIONS_COORDINATOR: 7,
    Role.ADMIN_ASSISTANT: 8,
    Role.PLUS_ONE: 99,
}
```

A module-level helper produces the Python sort key so the queryset path and the
`participants()` list path order identically:

```python
def roster_sort_key(role, last_name, first_name):
    rank = WorkgroupMembership.ROLE_RANK.get(role, WorkgroupMembership.ROSTER_DEFAULT_RANK)
    return (rank, (last_name or "").lower(), (first_name or "").lower())
```

### 2. `active_members()` — order the queryset

Annotate the rank with a `Case/When` built from `ROLE_RANK` (default
`ROSTER_DEFAULT_RANK`) and order by it, then last/first name:

```python
def active_members(self):
    whens = [When(role=r, then=Value(rank)) for r, rank in WorkgroupMembership.ROLE_RANK.items()]
    return (
        self.memberships.serving()
        .exclude(user__profile__is_persona=True)
        .select_related("user", "user__profile")
        .annotate(_role_rank=Case(*whens, default=Value(WorkgroupMembership.ROSTER_DEFAULT_RANK), output_field=IntegerField()))
        .order_by("_role_rank", "user__last_name", "user__first_name")
    )
```

This is the chokepoint the About page (`content.views._roster_members` →
`list(committee.active_members())`) and the committee/workgroup settings roster
read directly, so those surfaces inherit ordering with no further change.

### 3. `participants()` — sort the assembled list

`participants()` seeds a dict from `active_members()` (now ordered), then appends
auto-members and event registrants. After the list is assembled, sort it with
`roster_sort_key` using each entry's role + user name so derived members
interleave into the everyone-else tier alphabetically rather than being appended
at the end. (Confirm the entry shape during implementation — read the actual
`participants()` body — and derive `role` per entry, defaulting derived/no-role
entries to the everyone-else tier.)

### 4. Surfaces inherited for free

- **About page** — `content/views.py` `_roster_members` calls
  `committee.active_members()`; Board + Program Committee rosters now ordered.
- **Committee pages** — `Committee.active_members()` delegates to
  `workgroup.active_members()`.
- **Workgroup overview tab** — uses `participants()`.
- **Workgroup settings / manage-roster** — uses `list(wg.active_members())`.

No view or template edits are expected beyond what flows through 2 & 3.

## Testing

New tests under `workgroups/tests/`:

1. Committee with memberships added in scrambled order (member, treasurer,
   chair, secretary, co_chair, another member) → `active_members()` returns
   chair, co_chair, secretary, treasurer, then the two members alphabetical by
   last name.
2. Two members sharing a role (e.g. two co-chairs) → ordered alphabetically by
   last name, then first name.
3. `PLUS_ONE` sorts last.
4. `FACULTY` / `WEB_COORDINATOR` sort in the everyone-else tier (alphabetical),
   not as officers.
5. `participants()` on a group with derived (auto / registrant) members returns
   a correctly ordered combined list (officers first, rest alphabetical).

Keep the existing suite green (pytest) and ruff clean.

## Out of scope

- No new DB field, no migration.
- No change to `OFFICER_TITLES` relabeling or to which roles are considered
  "leads" for permissions (`LEAD_ROLES`).
- No faculty-float special-casing for seminars (rosters not displayed).
