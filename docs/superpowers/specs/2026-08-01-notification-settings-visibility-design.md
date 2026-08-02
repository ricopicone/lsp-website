# Hide notification categories that don't apply to the member

Task #491 follow-on. 2026-08-01.

## Problem

`/notifications/settings/` lists all 33 categories to everyone. A member who
will never review a payment plan, triage a suggestion, or take a referral still
sees rows for them, and the page reads as a wall of settings that mostly don't
apply. Every member sees "Tuition payment plans" even though only the Board
ever receives one.

## Design

### 1. `notifications/audience.py`

A new module owning one question: *should this member see a row for this
category?*

```python
AUDIENCE: dict[str, Callable[[User], bool]]

def applies(user, category) -> bool: ...
def visible_categories(user) -> list[str]: ...   # CATEGORY_META order preserved
```

A category absent from `AUDIENCE` is always visible — the safe default, so
adding a category never accidentally hides it. Superusers see everything.
Predicates import their gates lazily inside the function, so `categories.py`
stays a pure table and there is no import cycle.

This lives beside `categories.py` rather than inside `CategoryMeta` because it
is a different concern: `default_email_for` changes *delivery* (dispatch reads
it), `applies_to` changes only what the settings page *renders*. **Delivery is
untouched** — a hidden category still notifies normally if it ever fires, which
is what makes hiding safe.

### 2. One helper, both code paths

`settings_page` builds its rows from `visible_categories(request.user)`, and the
POST branch iterates the same call.

This is the correctness crux. Today the POST loop walks all of `CATEGORY_META`
and reads `request.POST.get(f"{category}__in_app")`, treating a missing key as
*off*. Rendering a subset without changing the save loop would silently write
`in_app=False, email=off` for every hidden category the first time a member
saved. Sharing one helper makes the two sets impossible to drift apart.

Sections that end up with no visible rows already drop out (`if sections[s]` in
the view).

### 3. The gated categories

Each was checked against every `notify()` call site that uses it; a category
with an audience that can't be captured crisply stays visible.

| Category | Visible to |
|---|---|
| `TUITION_PLAN_REVIEW` | Board members (`is_on_committee(user, "board")`) |
| `SUGGESTION_FILED` | Web Coordinator / Web Developer role holders |
| `REFERRAL_REQUEST` | Referral-list clinicians **or** the Referral Coordinator |
| `EXTERNAL_CONTROL_ANALYST` | `workgroups.permissions.is_meeting_of_analysts(user)` |
| `AVAILABILITY_REVIEW` | `availability.services.is_eligible(user.profile)` |
| `TUITION_REMINDER` | `user.profile.owes_tuition` |
| `TUITION_PLAN_DECISION` | `user.profile.owes_tuition` |

`REFERRAL_REQUEST` genuinely has two audiences — `referral_request()` notifies a
clinician, `referral_held()` notifies the coordinator — but both are crisply
gated, so the predicate is an OR rather than a reason to skip it.

**Deliberately not gated:**

- `CARTEL_PROPOSAL` — looks like a coordinator/PC queue, but
  `cartels.notifications.coordinator_feedback` also notifies `cartel.generator`,
  the member who started the cartel. Hiding it by role would hide it from
  someone who receives it.
- `EVENT_CHANGE_REVIEW`, `ADMISSIONS_APPLICATION` — same shape: reviewers *and*
  the submitter/applicant.
- Everything member-shaped (dues, balance, groups, cartels, Parlêtre, account)
  — these apply to essentially every member, and gating them would make the
  page churn as memberships change for no real gain.

### 4. Stored preferences are never touched

Hiding a row neither deletes nor rewrites the member's stored override. A member
who once chose something for a category they no longer qualify for keeps it, and
if they rejoin the Board the row reappears with their old choice intact.

## Testing

- A non-Board member sees no `tuition_plan_review` row; a Board member does.
- **The regression this exists to prevent:** a non-Board member with a stored
  `tuition_plan_review` preference POSTs the settings form; the stored value is
  unchanged afterwards, and the categories they *can* see still save correctly.
- A member who doesn't owe tuition sees neither tuition row; one who does sees
  both.
- The Referrals section disappears entirely for a member who is neither on the
  list nor the coordinator.
- A superuser sees every category.
- Structural: the rows rendered for a user equal `visible_categories(user)`, so
  render and save can't drift.
- Categories with no predicate resolve visible for everyone (default-open).

## Out of scope

- Any change to delivery. `notify()`, `resolve()`, and the digest are untouched.
- A collapsed "other notifications" section. Hidden means hidden.
- Gating the notification *feed* — this is the settings page only.
