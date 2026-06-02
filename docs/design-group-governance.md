# Design note — Group governance lifecycle (audit + open decisions)

A systematic audit of the **governance lifecycle** of every Workgroup-based
entity, across the dimensions that keep recurring as we build them. The point
is to make the *variation* and the *gaps* explicit, so the undefined cells
become decisions we fill deliberately rather than discover ad hoc.

Companion docs: `design-workgroups.md` (the shared layer) and
`design-workgroup-events.md` (the Workgroup-primary Event reframe). Memory:
`group-governance-audit`.

## How to read this

Two families fall out of the audit:

- **Offerings** — seminar, reading group, cartel. Proposed, term-bounded,
  registration-based. Their roster derives from faculty + paid/comped
  registrants (except cartels). They live on `/program/` by academic year.
- **Standing bodies** — committee, working group, Meeting of Analysts.
  Appointed, ongoing, Board/staff-governed. Roster is stored
  `WorkgroupMembership` rows.

Most silences cluster in the **standing-bodies** column, because **Cartel** is
the only entity that has received a full governance treatment (CART-4). Use
Cartel as the worked example when designing the others — but don't assume its
*answers* transfer; a working group is Board-created, not member-proposed.

**Status legend:** ✅ built & coherent · 🟡 partial / designed-not-built ·
⚙️ admin/shell only (no member-facing flow) · 🔴 undefined or silent.

## Lifecycle audit

### Primary dimensions

| Entity | Creation / Proposal | Approval | Registration / Joining | Administering | Events / Scheduling |
|---|---|---|---|---|---|
| **Seminar** (`Event`, SEMINAR) | ⚙️🟡 PC/staff build directly in program admin. Faculty *propose→PC approve* (M12.5) **designed, not built**. | 🟡 No approval of the seminar itself. Per-*registrant* faculty approval exists (`requires_faculty_approval`). | ✅ Full public registration: tiers, pricing codes, tuition-covered, sliding scale, optional faculty approval. | ✅ `can_edit_event` (faculty/PC/staff); faculty edit copy, mint codes, roster CSV; PC full edit. | ✅ `Session` + `generate_sessions` recurrence; per-class vs whole-seminar billing. |
| **Reading Group** | 🟡🔴 **Two conflicting paths**: standing `Workgroup` (admin-only, migration 0009) *vs* `Event(READING_GROUP)` (program admin). No rule for which; no member proposal. | 🔴 None (PC creates directly; M12.5 would cover the Event path). | 🟡 **Inconsistent**: Event path → paid registration; standing path → `open_join` self-join. | ✅/⚙️ Event path: as Event. Standing path: organizer role + member settings. | ✅ Event path: Sessions. Standing path: `WorkgroupMeeting` / `generate_event`. |
| **Cartel** | ✅ Any LSP member proposes (`cartels.propose`). Fully built (CART-4). | ✅ Program Committee approves/declines; Cartel Coordinator gives advisory feedback. | ✅ Three paths: seeded invitation, open application (member-gated acceptance), plus-one (internal + external). | ✅ Member-managed: generator edits while proposed; any member can close/archive, set plus-one. | 🟡🔴 No `Session`s; time-window only. Optional `generate_event`. No cadence concept. |
| **Working Group** | ⚙️🔴 Admin/shell only; thin attach-model, no UI. **Docs intent: Board creates** — not encoded anywhere. | 🔴 None (Board authority implicit). | 🔴 Appointed; no join/apply flow. | ⚙️🔴 Roster via Django admin only; **no permission helper, no edit UI**. | 🟡 `has_calendar/minutes/tasks/decisions` toggles on; `WorkgroupMeeting` exists but no wired UI. |
| **Committee** | ⚙️ Seed migration / admin; auto-provisions its Workgroup. No proposal flow (foundational by design). | 🔴 N/A (Board authority implicit). | ⚙️ Appointed (`add_member`); `is_on_committee` gate. No self-service. | 🟡 Roster via Workgroup admin; Board/PC/LSP-Staff committees gate *site* permissions; charter editable only in Django admin. | 🟡 Committees *organize* events (PC → special events) but have no own `Session` scheduling; `WorkgroupMeeting` for internal. |
| **Meeting of Analysts** | ⚙️ Built as a `Workgroup` w/ `auto_member_role=analyst`. **Absent from all planning docs.** | 🔴 N/A. | ✅ Automatic — every Analyst is a member, no action. | 🔴 **Undefined**: who chairs / administers it? | 🔴 **Undefined**: cadence? Relationship to `DAY_OF_ASSEMBLY`? |

### Additional dimensions (recommended — currently un-audited)

The five primary dimensions miss governance that is *also* varying
inconsistently. These belong in the audit:

| Entity | Exit / Leaving | Dissolution / Archival | Roster authority (who appoints chair/roles) | Lifecycle / cadence | Fees / tuition interaction |
|---|---|---|---|---|---|
| **Seminar** | Bounded by term | End of term | PC sets faculty | Annual program offering | Per-type blocking table (M7.5); tuition-covered exempts |
| **Reading Group** | Term (Event path) / `leave` (standing) | End of term / 🔴 standing undefined | 🔴 faculty or chair? | 🟡 muddled by dual path | Does *not* block on unpaid tuition (M7.5) |
| **Cartel** | 🔴 **no member-leave UI** (only generator-archive) | ✅ `archive()` | ✅ member-gated; plus-one defined | Time-window | Does *not* block on unpaid tuition (M7.5) |
| **Working Group** | ⚙️ admin-only | 🔴 undefined | 🔴 undefined | Standing | N/A |
| **Committee** | ⚙️ admin-only (end-date) | 🔴 undefined | 🔴 undefined | Standing | N/A |
| **Meeting of Analysts** | 🔴 (auto-derived; leaving = losing the role?) | 🔴 undefined | 🔴 undefined | Standing | N/A |

## Open decisions

Each maps to a 🔴/🟡 cell above. Fill these in inline as they're decided
(date + outcome), the way `design-workgroups.md` records its stage decisions.

### G1 — Seminar creation: proposal-mandatory or dual-path?
Today PC hand-builds seminars in the program admin. The faculty
proposal→PC-approval flow (M12.5) is fully *designed* but not built. Decide:
is the proposal path the **only** way to mint a seminar, or does direct PC
creation remain alongside it? (Cartel makes proposal mandatory; seminars may
warrant the escape hatch.)
**Decision (2026-06-01, SHIPPED):** dual path. Direct PC creation
(`program_admin_event_new`) stays; a faculty proposal flow (M12.5) was added on
top. Built as a standalone `events.SeminarProposal` (its own status), *not* a
`WorkgroupProposal` — that model is one-per-workgroup, which a continuing
seminar (workgroup already exists) and a pre-approval proposal (no workgroup
yet) can't satisfy. `approve()` mints the `Event` + `ensure_workgroup` +
`set_faculty`, handling new vs continuing (`continues_seminar`). See commit
`8ec49d9` (Phase F).

### G2 — Reading Group: pick one canonical model
The single biggest *inconsistency*, not just a silence. A reading group is
currently expressible **two** ways with no rule:
- standing `Workgroup(kind=reading_group)` with `open_join` (migration 0009,
  Freud Reading Group), and
- `Event(event_type=READING_GROUP)` via the program admin (auto-creates an RG
  workgroup, registration-based).

Decide the canonical shape (Event-backed-per-term like seminars/cartels, vs
standing self-join body), document when the other path is allowed (if ever),
and reconcile joining (paid registration vs `open_join`) and cadence to match.
**Decision (2026-06-01, SHIPPED):** canonical model is a **standing self-join
`Workgroup(kind=reading_group)`** with `open_join`; it may also carry optional
annual paid *terms* (`open_reading_group_term` → an `Event`) for fee-based
years. Built in the `keen-booping-ladybug` line and merged here (`4c95e3a`):
free standing groups use one-click join; a term, when opened, is the
registration cycle that `current_term`/active-vs-archive keys off. The
standalone Event-without-a-standing-group path is no longer how reading groups
are created.

### G3 — Working Group: full lifecycle
"Board creates" is the only documented bit and it's encoded nowhere. Define
the whole row:
- **Creation** — Board-initiated flow (UI? admin action? who is "the Board" in
  permission terms — the Board committee membership?).
- **Roster authority** — who appoints the chair and members.
- **Approval** — is there any, or is Board creation self-authorizing?
- **Scheduling** — does `WorkgroupMeeting` get a member-facing UI?
**Decision (2026-06-01, SHIPPED):** Board-gated, member-facing creation
(`WorkingGroup.objects.create_with_chair`): a Board-committee member (or LSP
staff) names the group, sets its chair, and seeds members — no approval step,
self-authorizing. Roster/leave/archive inherited from the generic Workgroup
manage surface (Phase B); scheduling via the existing `WorkgroupMeeting` tab
(chair/members manage — see G4/E). Commits `d042080` (Phase C) + `1c87cb3`.

### G4 — Roster authority across standing bodies (cross-cutting)
`WorkgroupMembership` has 11 roles (chair, co-chair, secretary, treasurer,
plus-one, faculty, organizer, referral/web-coordinator, admin-assistant) but
**no governance for who assigns or removes them** outside Cartel and
seminar-faculty. Define a single rule (likely: a group's chair + LSP Staff/Board
manage that group's roster) and a permission helper to back it, rather than
solving it per-app.
**Decision (2026-06-01, SHIPPED):** one primitive,
`workgroups.permissions.can_manage_workgroup(user, wg)` = Django superuser **|**
LSP Staff **|** Programming Committee **|** an active lead-role member (chair,
co-chair, plus-one, faculty, organizer) **|** Board. Used everywhere (roster
mutation, archive, charter, scheduling); `views._can_manage_workgroup` is a thin
adapter over it. A **last-lead orphan guard** forbids removing/demoting the sole
lead. Commits `1c87cb3` (Phase B) + `f907478` (Board folded in).

### G5 — Meeting of Analysts: reconcile built-vs-spec
Built in code (`Workgroup`, `auto_member_role=analyst`) but absent from every
planning doc. Define its administration (who chairs it), its cadence, and
whether it **is** the spring `DAY_OF_ASSEMBLY` or a distinct standing body.
**Decision (2026-06-01, SHIPPED):** a **distinct standing body** — the seeded
`meeting-of-analysts` committee with `auto_member_role=analyst` (every Analyst
auto-member). Day of Assembly stays a separate `Event(DAY_OF_ASSEMBLY)`; no
Event is attached to the MoA workgroup. Its chair is appointed via the generic
roster UI (no invented seed data), and its calendar is chair/Board-managed via
the schedule view/manage split (auto-derived analysts see it read-only). Commit
`f907478` (Phase E).

### G6 — Cartel scheduling
Cartels have no meeting cadence — time-window only, optional one-off
`generate_event`. Decide whether that's deliberate (self-directed study groups
don't need scheduling — a fine answer worth *recording*) or whether cartels
should gain a meeting concept.
**Decision (2026-06-01):** deliberate **non-feature**. Cartels stay
self-directed — no `Session`/cadence concept; the optional one-off
`workgroup.generate_event` remains the only escape hatch. Recorded so it isn't
re-litigated as an oversight.

### G7 — Member exit (cross-cutting)
Leaving is uneven: standing groups have `leave`/end-date, **Cartel has no
member-leave UI** (only generator-archive), committees/working groups are
admin-only. Decide whether self-service leaving is a universal Workgroup
capability (put it on `Workgroup`, per the layer principle) and which kinds opt
out.
**Decision (2026-06-01, SHIPPED):** universal `Workgroup.can_leave`/`leave`
(end-dates the stored membership). Only **stored** members can leave; purely
auto-derived rosters opt out by construction (seminar/reading-group registrants
lapse via the term axis; Meeting-of-Analysts analysts lose membership only by
losing the role). The **sole remaining lead cannot leave** (orphan guard).
Surfaced on every group's masthead. Commit `1c87cb3` (Phase B).

### G8 — Dissolution / archival (cross-cutting)
Only Cartel can be archived. Define how every other group *ends* (or is
explicitly standing-forever), and what happens to its channel/works/files on
archival.
**Decision (2026-06-01, SHIPPED):** a universal lifecycle axis —
`Workgroup.status` ∈ {active, archived} with `archive(by)`/`unarchive(by)`.
Archiving **freezes** the group read-only (`is_member` → False for everyone, so
posting/active-roster/workspace all freeze) **without** ending memberships or
deleting the channel/works/files; past members keep read-only access via
`has_archive_access`. The manage surface stays reachable to managers after
archive (gated on `can_manage_workgroup`, not membership) so it can be
reversed. `Cartel.archive` composes this with its proposal-status ARCHIVED so
the cartel stays listed on its program year. Commit `1c87cb3` (Phase B).

## Provenance

Built from a code audit (`workgroups`, `cartels`, `committees`, `events`,
`registrations`, `workinggroups`) cross-checked against the planning docs
(`../LSP-Website-Requirements-Spec.md` CART-*/PROG-*/REG-*/USR-*,
`../LSP-Website-Architecture-Phase1.md`, `../LSP-Website-Phase2-Plan.md` M12.5
proposal workflow, M14 cartel formation). Where code and spec diverge, the
divergence is itself logged as a decision above.
