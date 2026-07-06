# Formation app + My Formation enhancements

**Date:** 2026-07-06
**Tasks:** #356 (parent), #361 Control tracking, #363 external activities, #364 Advisor View. Also carries the architectural extraction Rico asked for during the design review.
**Branch:** `nimble-harbor`
**Source:** Annie Rogers / Diana Cuello / Garrett website-review meeting (task #345).

## Motivation

The formation domain (palimpsest / passage / traversée advancement, the advisor
relationship, control analyses) currently lives in the **`admissions`** app,
which also owns the intake pipeline (`Application`, interviews, Meeting-of-Analysts
review). These are two different concerns: **admissions** is how someone *enters*
the School; **formation** is a member's *ongoing journey* through it. They should
not share an app.

This spec (a) extracts a new **`formation`** app and moves the formation domain
into it, and (b) adds three member-facing formation records requested in the
review: **control-analysis tracking**, **external related activities**, and an
**Advisor View**.

## Scope of the extraction

### Moves to `formation`
- **Model:** `Advancement` (+ its palimpsest `FileField` storage) and
  `admissions/advancement.py` logic.
- **Member hub view:** `formation()` + `_formation_context()` and the
  `_formation_*` helpers, `tabs.py`, `formation.html`, and the `_tab_*.html`
  partials it composes. (See "Open decision: the hub" below.)
- **Advancement views:** `advancement`, `advancement_withdraw`,
  `palimpsest_download`, `advise_queue`, `advise_present`, `advancement_queue`,
  `advancement_detail`, `advancement_decide`.
- **URL names** (kept identical to avoid breaking `{% url %}` references
  site-wide): `formation`, `advancement`, `advancement_withdraw`,
  `palimpsest_download`, `advise_queue`, `advise_present`, `advancement_queue`,
  `advancement_detail`, `advancement_decide`. They keep their current paths
  (`/formation/…`, `/admin-tools/meeting-of-analysts/advancements/…`). The
  `app_name` namespace changes from `admissions:` to `formation:`, so
  cross-references are updated in one sweep.
- **Templates:** `formation.html`, `advancement_detail.html`,
  `advancement_queue.html`, `advise_queue.html`, `_tab_formation.html` (+ the
  other hub tab partials).
- **Tests:** `test_advancement.py`, `test_formation.py`, `test_my_lsp.py`.

### Stays in `admissions`
- **Models:** `Application`, `ApplicationInterview`.
- **Views:** `apply_start`, `apply`, `status`, `cv_download`, `review_queue`,
  `review_detail`, `review_assign`, `review_decide`, `review_report`,
  `review_remove_interview`, and the applications-coordinator console.
- Its templates (`apply*.html`, `review_*.html`, `status.html`) and admissions
  emails/notifications/services.

### Open decision (flag for spec review): the "My LSP" hub
`formation()` is really the member's personal hub — its tabs are Formation,
Tuition, Dues, Groups, Events, Works, Proposals, Profile, Suggestions — so it is
broader than formation, though formation is its spine and `/formation/` is its
URL. **Recommendation:** move the whole hub into `formation` (its identity is
`/formation/`; it already composes the other tabs from `payments`, `workgroups`,
etc. via imports, and that composition is unchanged by the move). The alternative
— leaving the hub in `admissions` and having it include a Formation tab rendered
from `formation` — creates a cross-app template dependency for little gain.
Confirm the recommendation during spec review.

## Migration strategy (no data loss)

`Advancement` has real rows and uploaded palimpsest files in prod, so we do **not**
recreate the table. The move uses Django's `SeparateDatabaseAndState`:

1. Create the `formation` app; define `Advancement` there with an explicit
   `Meta.db_table = "admissions_advancement"` (its current table name) so the DB
   object is untouched.
2. In `admissions`, a `SeparateDatabaseAndState` migration removes `Advancement`
   from `admissions`' migration *state* only (no SQL).
3. In `formation`, a matching `SeparateDatabaseAndState` migration adds
   `Advancement` to `formation`'s state only (no SQL).
4. New models (below) are ordinary `CreateModel` migrations in `formation`.

`FileField` `upload_to`/storage paths are preserved, so existing palimpsest files
resolve unchanged. Verify on a copy of the prod DB before deploy.

## New data model (all in `formation`)

### `ControlAnalysis` — member self-reported, no approval
- `member` → User
- `supervisor_name` (Char) — free text; supervisors are often external to LSP
- `modality` (choices: in_person / remote / hybrid)
- `start_date` (Date), `end_date` (Date, null=ongoing)
- `notes` (Text, blank)
- timestamps
- **Duration** = `start_date` → (`end_date` or today), summed across a member's
  entries for the progress meter.

### `ExternalActivity` — member self-reported, typed
- `member` → User
- `kind` (choices: course_taken / course_taught / presentation / publication /
  other) — subsumes the "taking vs teaching" role, so no separate role field
- `title` (Char), `venue` (Char, blank)
- `start_date` (Date), `end_date` (Date, null)
- `url` (URL, blank), `notes` (Text, blank)
- timestamps

### `AdvisorNote` — advisor-private
- `advisee` → User, `author` → User, `body` (Text), `created_at`
- **Visibility:** the advisee's current advisor(s) + staff. **Never the advisee.**

### `FormationSettings` — singleton, admin-editable
- `control_years_target` (PositiveInteger, default **6**)
- Keeps the requirement target out of code so it won't drift when the analysts
  revise formation requirements. (Control is measured in *years* — "minimum of
  six years of control analyses, or four years of ongoing dialogue" — not case
  count.)

## Member UI — the Formation tab

Two new sections on the existing Formation tab, member-owned CRUD (add / edit /
delete their own):

- **Control analyses:** a log (supervisor · date range · modality) plus a
  **progress meter** — total years across entries vs `control_years_target`, with
  helper text noting the "or 4 years of ongoing dialogue" alternative path. An
  ongoing entry (no `end_date`) counts up to today.
- **External activities:** the typed list, grouped/filterable by `kind`.

New site copy uses commas, not em dashes (per the task-#352 site-copy decision).

## Advisor View (#364)

- `/formation/advisees/` (name `advisees`) — lists the signed-in advisor's
  **current** advisees (via `accounts.advisor.current_advisor`).
- `/formation/advisees/<id>/` (name `advisee_detail`) — a **read-only** view of
  that advisee's formation record: advancement history, control log + progress,
  external activities, and groups; **plus** an advisor-notes panel to add/read
  `AdvisorNote`s.
- **Gate:** the advisee's current advisor **or** staff only. A stray member
  hitting the URL for someone who isn't their advisee gets 403/404.
- Entry point: the hub already surfaces an advisor's `advise_queue`; add an
  "Advisees" link alongside it for users who advise.

## Permissions & visibility (the invariants tests must lock)

- A member may create/read/update/delete **only their own** `ControlAnalysis` and
  `ExternalActivity`.
- A member **cannot** read another member's records.
- An **advisor** (current) or **staff** may **read** an advisee's records and
  create/read `AdvisorNote`s.
- A member **cannot** see `AdvisorNote`s about themselves.

## Testing

- Model math: duration of a closed entry; ongoing entry counts to today; progress
  = sum vs target; target read from `FormationSettings`.
- Extraction: `Advancement` rows survive the `SeparateDatabaseAndState` move
  (migration test on existing data); palimpsest download still works; all moved
  `{% url %}` names resolve under the `formation:` namespace.
- Visibility gates (each bullet in the section above), especially: member↔member
  blocked, advisor→advisee allowed, advisor note hidden from advisee.
- Hub still renders all tabs after the move (`test_my_lsp` / `test_formation`).

## Phasing (one plan, sequential phases)

1. **Extraction, no behavior change.** Create `formation`; move `Advancement`
   (table-preserving) + the hub + advancement/advise views + templates + tests;
   re-namespace `admissions:` → `formation:` for moved names; green test suite.
2. **Control-analysis tracking** (#361): model + `FormationSettings` + member CRUD
   + progress meter on the Formation tab.
3. **External activities** (#363): model + member CRUD + typed list.
4. **Advisor View** (#364): advisees list + read-only detail + `AdvisorNote`.

Each phase ships independently behind the same app, tests green at every step.

## Out of scope
- No approval workflow on control/external records (member self-reports, per the
  review — keeps human discretion, no new gate).
- No enforcement of formation requirements in software beyond the informational
  progress meter.
- Renaming the hub (e.g. to "My LSP") — the view/URL keep the `formation` name.
