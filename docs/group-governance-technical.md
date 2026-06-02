# Workgroup governance lifecycles — technical reference

How every Workgroup-based entity is created, approved, joined, administered,
scheduled, exited, and dissolved — and the shared primitives that implement it.
Audience: developers. Companions: `design-workgroups.md` (the shared layer),
`design-group-governance.md` (the audit + the G1–G8 decisions this implements),
`design-workgroup-events.md` (the Workgroup-primary Event reframe).

## The shared layer

Every group kind is a `workgroups.Workgroup` (`workgroups/models.py`) with a
`kind` ∈ {`cartel`, `working_group`, `committee`, `seminar`, `reading_group`}.
Concrete domain models *attach* one via `OneToOneField`:

| Kind | Attach model | Notes |
|---|---|---|
| cartel | `cartels.Cartel` | guiding question, coordinator feedback, plus-one |
| working_group | `workinggroups.WorkingGroup` | thin |
| committee | `committees.Committee` | charter, public page |
| seminar | *(none — `events.Event` references the workgroup)* | term-based offering |
| reading_group | *(none — standing, or an `events.Event` term)* | standing self-join |

The Workgroup owns: the roster (`WorkgroupMembership`), a Parlêtre channel,
shared works/files, a landing/Workspace page, capability toggles
(`has_channel/works/files/calendar/minutes/tasks/decisions`), two visibility
axes (`landing_visibility`, `content_visibility`), and a lifecycle `status`.

**Principle:** add a feature several kinds could want to `Workgroup` first.

## Three orthogonal access axes

Membership/access is the composition of three independent axes — keep them
distinct when reasoning about a kind:

1. **Governance / roster axis** (Phase A) — `WorkgroupProposal` /
   `WorkgroupInvitation` / `WorkgroupJoinRequest` gate entry to the **stored**
   `WorkgroupMembership` roster. Independent of payment/term.
2. **Lifecycle axis** (Phase B) — `Workgroup.status` ∈ {`active`, `archived`}.
   Archiving freezes the group: `is_member()` returns `False` for everyone (so
   posting / active roster / workspace all freeze), while memberships persist
   and past members keep read-only `has_archive_access()`.
3. **Term axis** (offering kinds only, = `OFFERING_KINDS` {seminar,
   reading_group}) — `is_member()` derives from `current_term()`: the active
   members are the current term's paid/comped registrants. Past-term attendees
   lapse to archive-only automatically and must re-enroll.

`Workgroup.is_member(user)` is the one access primitive the cross-cutting apps
(Parlêtre, works) call. It checks, in order: authenticated → not archived →
`auto_member_role` (derived, e.g. analysts) → stored active membership →
(offering) current-term registrant. `has_archive_access(user)` grants read-only
access to active members, the still-active roster of an *archived* group, and
(offering) any past-term paid/comped registrant.

## Governance primitives (Phase A — `workgroups/models.py`)

- **`WorkgroupProposal`** (OneToOne → Workgroup) — `status`
  (proposed/open/declined/archived), `proposed_by`, `reviewed_by`,
  `reviewed_at`, `review_note`. Methods `approve(reviewer, *,
  publish_visibility=MEMBERS)` (flips landing to publish), `decline(reviewer,
  note)`, `resubmit()`.
- **`WorkgroupInvitation`** (FK → Workgroup) — seeded specific-member invite;
  `accept()` adds the member.
- **`WorkgroupJoinRequest`** (FK → Workgroup) — an applicant's request;
  `accept(decided_by)` / `decline(decided_by)` (member-gated growth).
- **`Workgroup`** workflow methods: `request_to_join`, `accept_request`,
  `decline_request`, `accept_invitation`, `governance_state(user)` (the generic
  subset of context a detail page needs), `_add_member`.

**Cartel** is the canonical consumer: its `status`/`generator`/`reviewed_*`
fields are proxy properties onto `workgroup.proposal`; `CartelInvitation` /
`CartelJoinRequest` are kept importable as aliases of the generic models.

### Management permission — the single source of truth

`workgroups/permissions.py`:

```python
can_manage_workgroup(user, wg)  # superuser | LSP Staff | Programming Committee
                                # | active lead-role member | Board
is_board(user)                  # active member of the `board` committee
```

`LEAD_ROLES` = chair, co-chair, plus-one, faculty, organizer
(`WorkgroupMembership.LEAD_ROLES`). `views._can_manage_workgroup(wg, user)` is a
thin adapter. Every management action (roster mutation, archive, charter,
scheduling) routes through this.

## Lifecycle, exit, roster mutation (Phase B — `workgroups/models.py`)

```python
wg.archive(by) / wg.unarchive(by)          # lifecycle axis; never ends memberships
wg.is_archived                             # property
wg.can_leave(user) / wg.leave(user)        # stored members only; orphan-guarded
wg.add_member(user, role=...) / wg.remove_member(user) / wg.set_role(user, role)
wg.lead_members()                          # active LEAD_ROLES memberships
```

**Orphan guard** (`_would_orphan`): the sole remaining lead cannot leave, be
removed, or be demoted out of a lead role. Manager surface (roster + lifecycle
controls) lives on the Workspace **Settings** tab, reachable whenever
`can_manage_workgroup` is true — *including after archive*, so dissolution is
reversible (`workgroups/views.py`, `_tab_settings.html`).

Enforcement chokepoints that compose with the axes: `parletre/permissions.py`
(`channel_visible` = member OR archive-access; `channel_can_post` = member
only) and `works/models.py` (`Work._visible_at` GROUP = member OR archive
access; `Work.listing_for` scopes GROUP works to member groups).

## Per-kind lifecycle

| Kind | Creation | Approval | Joining | Administering | Scheduling | Exit / dissolution |
|---|---|---|---|---|---|---|
| **Cartel** | Any LSP member proposes (`cartels.propose`) | Program Committee `approve/decline`; Cartel Coordinator advisory feedback | Seeded invitation · open application (member-gated) · plus-one (internal/external) | Members manage; close/reopen; set plus-one | None (deliberate, G6); optional one-off `generate_event` | Member `archive()` → proposal ARCHIVED + `workgroup.archive` |
| **Working Group** | Board-gated member-facing `WorkingGroup.objects.create_with_chair` (name, chair, seed members) | None — Board creation self-authorizes | Manager adds to roster (`roster_add`) | Chair (lead) + Board + staff via Settings tab | `WorkgroupMeeting` (members + managers) | `leave` (orphan-guarded) · `archive` |
| **Committee** | Seed migration / staff (foundational) | N/A | Appointed (`add_member`) | Charter edit (`committees.edit_charter`) + roster via Settings, `can_manage` (lead/PC/LSP-staff/Board) | `WorkgroupMeeting` | `archive` (manager) |
| **Seminar** | Dual path: PC builds in program admin **or** faculty propose → PC approve (`events.SeminarProposal.approve` mints the Event) | Per-seminar: PC on the proposal. Per-registrant: optional `requires_faculty_approval` | Registration (paid/comped → derived roster); faculty stored as `FACULTY` | Faculty edit copy + mint pricing codes + roster CSV; PC full edit | `Session` + `generate_sessions` for the public event; `WorkgroupMeeting` for the workspace | Term axis: re-enroll each year, else archive-only. Standing workgroup persists across terms |
| **Reading Group** | Standing self-join `Workgroup(kind=reading_group)`; optional annual paid term (`open_reading_group_term`) | None (free) / N/A | One-click `open_join` (free) · registration (paid term) | Organizers (lead) manage; open terms | `WorkgroupMeeting`; term `Session`s if a paid term | `leave` · term lapse · `archive` |
| **Meeting of Analysts** | Seeded `committee` with `auto_member_role=analyst` | N/A | Automatic — every Analyst is a member (derived) | Chair appointed via roster UI; chair/Board/staff manage; schedule chair-managed (analysts read-only) | `WorkgroupMeeting`, manager-only (`_can_schedule`) | `archive` (manager) |

### Scheduling gate

`views._can_schedule(wg, user)` = manager **or** stored member. This keeps the
Meeting of Analysts (auto-derived analysts) chair-managed while cartel/working-
group/committee members keep their member-open schedule. The Schedule tab shows
the cadence to anyone with the tab; the add form + delete are gated on
`can_schedule`.

### Seminar proposal flow (M12.5 — `events/`)

`events.SeminarProposal` is a **standalone** typed record (its own status), not
a `WorkgroupProposal` — that model is one-per-workgroup, which a *continuing*
seminar (workgroup already exists) and a pre-approval proposal (no workgroup
yet) can't satisfy. `approve(reviewer)`:

1. `Program.objects.get_or_create(academic_year=...)` (derived from
   `start_date`).
2. Create the `Event` (slug de-duped; `status=OPEN`).
3. Continuing → attach `continues_seminar` workgroup; else `set_faculty()` calls
   `ensure_workgroup()`, minting the standing SEMINAR workgroup + channel.
4. Record `minted_event`, flip to APPROVED.

Date validation (`SeminarProposalForm.clean`): `end_date > start_date` and not
in the past — otherwise `current_term()` would never activate the term.
Gating: propose = `profile.is_faculty`; decide = `is_program_committee`. Review
queue is a "Proposals" tab in the PC admin.

## Migrations of record

`workgroups/0008_workgroupproposal…`, `0012_merge…`, `0013_…archived…`;
`cartels/0006_move_to_generic` (data copy, idempotent + empty-db no-op),
`0007_drop_legacy_fields`; `events/0019_seminarproposal`.

## Adding a new group kind / feature

1. Add the `Kind` (+ `KIND_TOGGLE_DEFAULTS`, `ROSTER_VISIBILITY`, and whether
   it's an `OFFERING_KIND`).
2. Reuse the governance primitives — don't reinvent propose/approve/join.
3. Gate management with `can_manage_workgroup`; gate exit with `can_leave`.
4. If it has a member-facing template dir, add it to the Dockerfile stage-2
   `COPY` list (Tailwind scans it at build).
5. Keep `cartels/tests.py` style behavior-preserving tests green.
