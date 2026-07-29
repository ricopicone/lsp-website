# Open the advisor pool to all eligible analysts

**Task:** #483 — "Open up advisor selection to all analysts for now so that people
who already have advisors who aren't currently accepting new advisees can still
select their advisors."
**Date:** 2026-07-29

## Problem

`accounts.advisor.eligible_advisors` drops any analyst carrying an open
availability span of `status="no"` for the `advisor` function. The intent was to
keep members from picking someone who has said they are not taking new advisees.
The effect is that a member whose *existing* advisor has closed their door cannot
name them, because the picker is the only way an advisorship gets recorded.

There is no prior `Advisorship` row to grant an exception from: at launch almost
every real advisorship predates the site. The intake survey's advisor question
("Who is your current advisor?") is precisely a request to record a relationship
that already exists off-site, and it feeds off the same filtered pool. So the
filter fails hardest exactly where it is most consequential.

The information the filter encodes is still worth showing. It just must not
block.

## Decision

Declared availability becomes **advisory** for advisor selection: it labels the
picker, it no longer gates it. Every role-eligible analyst is selectable,
grouped so the member can see who said what.

This is a plain code change, not a toggle. "For now" is served by a revert; a
`FormationSettings` boolean would add a field, a migration, and a branch to test
both ways for a decision the school is unlikely to reverse quietly.

Availability's own surfaces do not change. `/directory/availability/?only=advisor`
(linked from the account-ready email as "these analysts are currently available
to advise") still lists only analysts who said yes. That page is the
recommendation; the picker is the record.

## Design

### `accounts/advisor.py`

**`eligible_advisors(advisee)`** — drop the `.exclude(...)` clause covering
`profile__availability_spans__status="no"`. The pool becomes: `is_active`,
`profile__is_persona=False`, `standing=ACTIVE`, `role` in
`advisor_roles_for(advisee.profile.role)`, minus the advisee. The docstring
records why availability no longer filters.

**`advisor_choice_groups(advisee)`** replaces `advisor_availability_split`.
Returns an ordered list of `(group_label, [users])`:

1. `Available to advise` — an open advisor span with status `yes`
2. `Unknown availability` — no declared status: no open advisor span, an
   explicit `unknown` span, or a scholar-track advisor (who carry no spans at
   all)
3. `Not currently accepting new advisees` — an open advisor span with status `no`

Rules:

- Empty groups are omitted.
- The query's ordering (last name, first name, email) is preserved within each
  group.
- One query over open advisor spans builds a `{user_id: status}` map; the user
  list is partitioned from it. `AvailabilitySpan` holds at most one open span
  per (profile, function) — a DB constraint backs that invariant — so the map
  has one entry per analyst and no precedence rule is needed. The `availability`
  import stays lazy, as it is today, to avoid a load-time cycle.
- A *closed* `no` span (an `end_date` set) reads as unknown, unchanged from
  today's semantics.
- The three labels are module constants (`AVAILABLE_LABEL`, `UNKNOWN_LABEL`,
  `UNAVAILABLE_LABEL`) so the picker and its tests can't drift.

`advisor_availability_split` has two callers, `AdvisorSelectForm` and its test,
so it is replaced rather than kept alongside.

**`set_advisor`** is untouched. The chosen analyst gets the existing bell
notification and preference-gated email whatever their declared availability.
That is deliberate: for the already-advising case, that notification is the
record of what the member did.

### `accounts/forms.py` — `AdvisorSelectForm`

`field.queryset` stays `eligible_advisors(advisee)`, which is now the wider pool,
so posting a not-accepting analyst validates. `field.choices` becomes the blank
`("", "Select an advisor…")` option followed by `advisor_choice_groups(advisee)`
rendered as `<optgroup>`s.

### `accounts/views.py` — `intake_survey` and `accounts/templates/accounts/survey.html`

The `advisors` context value becomes `advisor_groups`, a list of
`(label, users)`; the template renders `<optgroup>`s instead of a flat option
list. The POST path already re-filters the submitted pk through
`eligible_advisors`, so it inherits the wider pool with no change.

### Copy

No block, no confirmation step, no warning banner. The group label is the whole
disclosure, per the do-not-over-automate principle. The Formation tab's intro
already tells members the School encourages speaking with a prospective Advisor
first. One sentence joins the help text under the select:

> Analysts who aren't taking new advisees are still listed, so you can name an
> Advisor you already work with.

Member-facing copy, so commas rather than em dashes.

## Tests

`accounts/test_advisor.py`:

- `test_eligible_advisors_excludes_only_advisor_unavailable` inverts into an
  *includes* test: an analyst with an open advisor `status="no"` span is now in
  the pool. It keeps its existing assertion that a `no` on a *different*
  function is irrelevant to the advisor pool.
- The split test becomes a three-way group test: yes / unknown / no land in the
  right groups in that order, and empty groups are omitted.
- A group test covers empty groups being omitted, and a closed `no` span reading
  as unknown.
- A form test asserts all three optgroup labels render and that posting a
  not-accepting analyst's pk validates; a view test posts to `advisor_select` and
  asserts the advisorship is recorded.

`accounts/test_survey.py`: `test_survey_sets_advisor` passes unchanged; two new
tests cover the survey picker rendering the not-accepting group and recording a
choice from it.

## Out of scope

- No `FormationSettings` toggle (see Decision).
- The control-analysis School-analyst dropdown never filtered on availability
  and is not touched.
- The availability app, its reminders, and the availability directory page are
  unchanged.
