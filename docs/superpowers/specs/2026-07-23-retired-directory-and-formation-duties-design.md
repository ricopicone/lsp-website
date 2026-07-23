# Retired — Directory Indicator + Formation-Duty Exclusion — Design (task #451 follow-on)

**Date:** 2026-07-23
**Status:** Approved, ready for implementation plan
**Branch:** silver-quartz
**Builds on:** the shipped New User Statuses feature (`2026-07-22-new-user-statuses-design.md`).

## Problem

Two gaps in the just-shipped Retired standing:

1. **Retired isn't indicated in the Directory.** A retired member appears in the
   directory looking like any active member. There should be a visible "Retired"
   marker (parallel to the deceased "In memoriam" marker).
2. **Retired members can still hold formation duties.** Retired analysts/scholars
   should not be assignable to — or continue serving in — the school's
   training/formation roles.

## Findings (current state)

"Formation duties" span several surfaces. Most already require **active standing**
and so already exclude retired:

- **Advisor selection** — `accounts/advisor.py:eligible_advisors` filters
  `profile__standing=ACTIVE` (line 41). ✓ already excludes retired.
- **Control analyst** ("Analyst of the School" dropdown) —
  `formation/forms.py:ControlAnalysisForm` filters `standing=ACTIVE` (line 111). ✓
- **Admissions interviewer** — `admissions/forms.py:analyst_pool` filters
  `standing=ACTIVE` (line 30); `admissions/permissions.py:is_analyst` checks
  `standing == ACTIVE` (line 36). ✓

Two surfaces filter by **role only**, so retired slips through:

- **Availability table** — `availability/services.py:eligible_profiles()` filters
  `role__in=AVAILABILITY_ROLES` with no standing gate. A retired analyst still
  gets an availability row (the plumbing behind the "available / not" spans on the
  advisor + interviewer pickers).
- **Meeting of Analysts** — the analyst body that makes admissions/advancement
  decisions. Its membership is **role-derived** through the generic `Workgroup`
  `auto_member_role` mechanism, which reads `profile.role` + `is_active` but **not**
  standing:
  - `workgroups/permissions.py:meeting_of_analysts_members()` (line 121)
  - `workgroups/models.py:Workgroup.is_member` (line 380, via `_user_role`)
  - `workgroups/models.py:Workgroup.participants` role-branch (line 427)
  - other `auto_member_role` readers: `workgroups/models.py:440`, `:876`,
    `workgroups/membership.py:185` (`groups_for`), `workgroups/views.py:558`.

**Blast radius of the Workgroup change:** exactly one workgroup sets
`auto_member_role` today — the Meeting of Analysts committee
(`committees/migrations/0009_meeting_of_analysts_auto_member`). No other group is
affected. Requiring active standing is the correct default for any future
role-derived group anyway.

## Decisions

- **Uniform rule:** formation eligibility everywhere means `standing == ACTIVE`.
  This excludes retired **and** on-leave / resigned / removed (and, via
  `is_active`, deceased). We tighten the two role-only surfaces (availability,
  Meeting of Analysts) to match how advisor/control/interviewer already work,
  rather than introducing a separate exclude-set.
- **Meeting of Analysts is in scope:** retired analysts drop out of membership,
  the permission check, and the participant/roster list. Gate the standing in the
  generic `Workgroup` role-derivation so all three agree.
- **Directory indicator only:** the "Retired" marker is informational. Unlike
  deceased, retired members keep their contact info / listing intact (they are
  still members). Retired members are already excluded from the Find-an-Analyst
  map + referral pool (shipped earlier), so no referral CTA change is needed here.

## Design

### Part A — Directory "Retired" indicator
- Add `Profile.is_retired` property (`standing == Standing.RETIRED`) for template
  clarity.
- Render a small **"Retired"** label on the directory card
  (`accounts/templates/accounts/directory.html`) and detail
  (`accounts/templates/accounts/directory_detail.html`), placed like the existing
  deceased "In memoriam" marker. Member-facing copy (commas, no em dashes);
  DaisyUI semantic tokens. If a member were somehow both retired and deceased, the
  deceased "In memoriam" marker takes precedence (deceased is the terminal state).

### Part B — Formation-duty exclusion (active-standing gate)
1. **Availability** — `availability/services.py:eligible_profiles()`: add
   `standing=Profile.Standing.ACTIVE` (and, for consistency with the other
   formation queries, `user__is_active=True` + `is_persona=False`). This is the
   single gate the import, coordinator console, and directory table all use, so
   one change covers them.
2. **Meeting of Analysts / Workgroup role-derivation** — require active standing
   wherever `auto_member_role` membership is derived:
   - `workgroups/permissions.py:meeting_of_analysts_members()` — add
     `profile__standing=Profile.Standing.ACTIVE` to the analyst queryset.
   - `workgroups/models.py:Workgroup.is_member` — the `auto_member_role` branch must
     additionally require the user be active-standing (and `is_active`,
     non-persona) — not just role match.
   - `workgroups/models.py:Workgroup.participants` role-branch (line 427) — add
     `profile__standing=Profile.Standing.ACTIVE`.
   - Audit the remaining `auto_member_role` readers (`models.py:440`, `:876`,
     `membership.py:185`, `views.py:558`) and apply the same active-standing gate
     so membership, roster, participants, and "my groups" all agree. Prefer a
     single shared predicate/queryset helper on `Workgroup` (e.g.
     `_auto_member_filter()` returning the role+standing+active+persona criteria)
     to avoid drift across these call sites.

The already-active-gated surfaces (advisor, control analyst, admissions
interviewer) need **no change**.

## Testing
- Directory: a retired member's card + detail render the "Retired" marker; an
  active member's do not; a deceased member still shows "In memoriam" (precedence).
- Meeting of Analysts: a retired analyst is NOT in `meeting_of_analysts_members()`,
  `is_meeting_of_analysts(user)` is False, `Workgroup.is_member`/`participants`
  exclude them; an active analyst is still included.
- Availability: `eligible_profiles()` excludes a retired analyst, includes an
  active one; the coordinator/import/directory surfaces that read it follow.
- Regression: advisor/control-analyst/interviewer pools unchanged (still exclude
  retired, still include active).

## Out of scope
- Changing on-leave / emeritus behavior beyond what the uniform active-standing
  rule already implies on the two tightened surfaces.
- The referral add-clinician picker (`referrals/forms.py`) — referral, not
  formation; retired members are already auto-delisted from the referral pool.
- Cleaning up existing stored availability rows for now-retired analysts (the
  eligibility gate makes them inert; no migration needed).
