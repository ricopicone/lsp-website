# Workgroup governance lifecycles — technical reference

How every Workgroup-based entity is created, approved, joined, administered,
scheduled, exited, and dissolved, and the shared primitives behind it.
Audience: developers. Companions: `design-workgroups.md` (the shared layer),
`design-group-governance.md` (the audit + the G1–G8 decisions this implements),
`design-workgroup-events.md` (the Workgroup-primary Event reframe). The
plain-language version is the staff guide (`core/docs/groups-guide.md`).

## The shared layer

A `workgroups.Workgroup` (`workgroups/models.py`) is the substrate for **five
kinds** (`Workgroup.Kind`): `cartel`, `working_group`, `committee`, `seminar`,
`reading_group`. Concrete domain models *attach* one via `OneToOneField`; the
Board, the Programming Committee, and the Meeting of Analysts are *instances* of
the committee kind, not kinds of their own.

| Kind | Attach model | Notes |
|---|---|---|
| cartel | `cartels.Cartel` | guiding question, coordinator feedback, plus-one |
| working_group | `workinggroups.WorkingGroup` | thin |
| committee | `committees.Committee` | charter, public page; instances incl. Board, PC, Meeting of Analysts |
| seminar | *(`events.Event` references the workgroup)* | term-based offering |
| reading_group | *(standing, or an `events.Event` term)* | standing self-join |

The Workgroup owns the roster (`WorkgroupMembership`), a Parlêtre channel,
shared works/files, a Workspace page, capability toggles
(`has_channel/works/files/calendar/minutes/tasks/decisions`), two visibility
axes (`landing_visibility`, `content_visibility`), and a lifecycle `status`.
**Add a feature several kinds could want to `Workgroup` first.**

## Three orthogonal access axes

`Workgroup.is_member(user)` — the one access primitive the cross-cutting apps
(Parlêtre, works) call — composes three independent axes:

1. **Governance / roster** (Phase A): `WorkgroupProposal` /
   `WorkgroupInvitation` / `WorkgroupJoinRequest` gate entry to the **stored**
   `WorkgroupMembership` roster.
2. **Lifecycle** (Phase B): `Workgroup.status` ∈ {`active`, `archived`}.
   Archiving freezes the group — `is_member()` → `False` for everyone (posting,
   active roster, and workspace all gate on it) — without ending memberships.
3. **Term** (offering kinds only, `OFFERING_KINDS` = {seminar, reading_group}):
   `is_member()` derives from `current_term()` — active members are the current
   term's paid/comped registrants; past-term attendees lapse automatically.

`is_member` checks, in order: authenticated → not archived → `auto_member_role`
(derived, see below) → stored active membership → (offering) current-term
registrant. `has_archive_access(user)` grants read-only access to active
members, the still-active roster of an *archived* group, and (offering) any
past-term paid/comped registrant.

**Auto-membership** is a Workgroup feature, not a kind: set `auto_member_role`
to a Profile role and everyone with that role is a derived member (no stored
rows). The Meeting of Analysts is the committee that uses it (`role=analyst`).

## Governance primitives (Phase A — `workgroups/models.py`)

- **`WorkgroupProposal`** (OneToOne → Workgroup) — `status`
  (proposed/open/declined/archived), `proposed_by`, `reviewed_by/at`,
  `review_note`; `approve(reviewer, *, publish_visibility=MEMBERS)`,
  `decline(reviewer, note)`, `resubmit()`.
- **`WorkgroupInvitation`** (FK) — seeded invite; `accept()` adds the member.
- **`WorkgroupJoinRequest`** (FK) — applicant request; `accept(decided_by)` /
  `decline(decided_by)` (member-gated growth).
- **`Workgroup`** workflow methods: `request_to_join`, `accept_request`,
  `decline_request`, `accept_invitation`, `governance_state(user)`,
  `_add_member`.

**Cartel** is the canonical consumer: its `status`/`generator`/`reviewed_*` are
proxy properties onto `workgroup.proposal`; `CartelInvitation` /
`CartelJoinRequest` are aliases of the generic models.

### Management permission — single source of truth

`workgroups/permissions.py`:

```python
can_manage_workgroup(user, wg)  # superuser | LSP Staff | Programming Committee
                                # | active lead-role member | Board
is_board(user)                  # active member of the `board` committee
```

`LEAD_ROLES` = chair, co-chair, faculty, organizer. The cartel **plus-one is
not a lead** — it's a guest; a cartel is run collectively by its members
(cartel close/archive/accept gate on `cartel.is_member`, not on a lead role).
`views._can_manage_workgroup(wg, user)` is a thin adapter. Every generic
management action (roster mutation, archive, charter, scheduling) routes through
`can_manage_workgroup`.

## Lifecycle, exit, roster mutation (Phase B — `workgroups/models.py`)

```python
wg.archive(by) / wg.unarchive(by)          # lifecycle axis; never ends memberships
wg.is_archived
wg.can_leave(user) / wg.leave(user)        # stored members only; orphan-guarded
wg.add_member(user, role=...) / wg.remove_member(user) / wg.set_role(user, role)
```

**Orphan guard** (`_would_orphan`): the sole remaining lead can't leave, be
removed, or be demoted out of a lead role. The manager surface (roster +
lifecycle controls) is on the Workspace **Settings** tab, reachable whenever
`can_manage_workgroup` is true — *including after archive*, so dissolution is
reversible (`workgroups/views.py`, `_tab_settings.html`).

Enforcement chokepoints that compose with the axes: `parletre/permissions.py`
(`channel_visible` = member OR archive-access; `channel_can_post` = member
only) and `works/models.py` (`Work._visible_at` GROUP = member OR archive
access; `Work.listing_for` scopes GROUP works to member groups).

## Per-kind lifecycle

| Kind | Creation | Approval | Joining | Administering | Scheduling | Exit / dissolution |
|---|---|---|---|---|---|---|
| **Cartel** | Any LSP member proposes (`cartels.propose`) | PC `approve/decline`; Cartel Coordinator advisory feedback | Seeded invitation · open application (member-gated) · plus-one (internal/external) | Members; close/reopen; set plus-one | None (deliberate, G6); optional one-off `generate_event` | Member `archive()` → proposal ARCHIVED + `workgroup.archive` |
| **Working Group** | Board-gated `WorkingGroup.objects.create_with_chair` (name, chair, seed members) | None — Board creation self-authorizes | Manager adds to roster (`roster_add`) | Chair + Board + staff via Settings tab | `WorkgroupMeeting` (members + managers) | `leave` (orphan-guarded) · `archive` |
| **Committee** | Seed migration / staff (foundational) | N/A | Appointed (`add_member`) | Charter edit (`committees.edit_charter`) + roster via Settings, `can_manage` | `WorkgroupMeeting` | `archive` (manager) |
| **Seminar** | Dual path: PC builds in program admin **or** faculty propose → PC approve (`events.SeminarProposal.approve` mints the Event) | Per-seminar: PC on the proposal. Per-registrant: optional `requires_faculty_approval` | Registration (paid/comped → derived roster); faculty stored as `FACULTY` | Faculty edit copy + mint pricing codes + roster CSV; PC full edit | `Session` + `generate_sessions` (public event); `WorkgroupMeeting` (workspace) | Term axis: re-enroll yearly, else archive-only; standing workgroup persists |
| **Reading Group** | Standing self-join `Workgroup(kind=reading_group)`; optional annual paid term (`open_reading_group_term`) | None (free) / N/A | One-click `open_join` (free) · registration (paid term) | Organizers + staff/PC; open terms | `WorkgroupMeeting`; term `Session`s if paid | `leave` · term lapse · `archive` |

Committee instances (Board, PC, Meeting of Analysts) follow the committee row;
the Meeting of Analysts adds `auto_member_role=analyst`, so its roster is
derived and joining is automatic.

### Scheduling gate

`views._can_schedule(wg, user)` = manager **or** stored member. This keeps the
Meeting of Analysts (auto-derived analysts) chair-managed while
cartel/working-group/committee members keep their member-open schedule. The
Schedule tab shows the cadence to anyone with the tab; the add form + delete are
gated on `can_schedule`.

### Seminar proposal flow (M12.5 — `events/`)

`events.SeminarProposal` is a **standalone** typed record (its own status), not
a `WorkgroupProposal` — that model is one-per-workgroup, which a *continuing*
seminar (workgroup already exists) and a pre-approval proposal (no workgroup
yet) can't satisfy. `approve(reviewer)`:

1. `Program.objects.get_or_create(academic_year=...)` (derived from
   `start_date`).
2. Create the `Event` (slug de-duped; `status=OPEN`).
3. Continuing → attach `continues_seminar`; else `set_faculty()` calls
   `ensure_workgroup()`, minting the standing SEMINAR workgroup + channel.
4. Record `minted_event`, flip to APPROVED.

`SeminarProposalForm.clean` requires `end_date > start_date` and not in the past
(else `current_term()` never activates the term). Gating: propose =
`profile.is_faculty`; decide = `is_program_committee`. The PC review queue is a
"Proposals" tab in the program admin.

## Migrations of record

`workgroups/0008_workgroupproposal…`, `0012_merge…`, `0013_…archived…`;
`cartels/0006_move_to_generic` (data copy, idempotent + empty-db no-op),
`0007_drop_legacy_fields`; `events/0019_seminarproposal`.

## Adding a kind or feature

1. Add the `Kind` (+ `KIND_TOGGLE_DEFAULTS`, `ROSTER_VISIBILITY`, and whether
   it's an `OFFERING_KIND`).
2. Reuse the governance primitives — don't reinvent propose/approve/join.
3. Gate management with `can_manage_workgroup`; gate exit with `can_leave`.
4. Add any new member-facing template dir to the Dockerfile stage-2 `COPY` list
   (Tailwind scans it at build).
5. Keep the behavior-preserving `cartels/tests.py` green.
