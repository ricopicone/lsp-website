# Control-analyses accounting — design (task #415)

**Status:** approved design, pre-implementation
**Date:** 2026-07-11
**App:** `formation` (with small touches in `accounts`, `admissions`, `core`, `notifications`)

## Problem

The current control-analysis feature (`formation.ControlAnalysis`) is a flat,
self-reported log with a single "total years" progress bar toward one target
(`FormationSettings.control_years_target`, default 6). It misses the actual
formation requirement, which is structured and background-dependent:

- **Clinical background:** two control analyses — **one for at least 4 years**
  and **one for at least 2 years**.
- **Academic (non-clinical) background:** three control analyses — **one for at
  least 4 years** and **two for at least 2 years**.

These analyses may run **simultaneously** (overlapping dates are fine). The
requirement is **per-relationship, not cumulative**: "one analysis for at least
4 years" means a single analyst relationship reaching 4 years — you cannot add
two shorter analysts together to satisfy one slot.

Two further gaps:

1. The supervisor is free text. Members should pick from a dropdown of the
   School's Analysts, or request authorization for an **external** control
   analyst.
2. Authorizing an external control analyst is a real **approval process** owned
   by the **Meeting of the Analysts** — currently nonexistent.

## Design overview

Five pieces, built in order:

1. **Background attribute** on `Profile` (clinical vs. academic) driving how
   many control analyses are required.
2. **Structured requirement + sub-bars** — tag each entry `4-year` or `2-year`
   (freely swappable), keep the Total bar, add per-slot sub-bars.
3. **Analyst selection** — dropdown of School Analysts on the control form.
4. **External-control-analyst authorization** — new model + request form +
   Meeting-of-the-Analysts approval queue + notifications.
5. **Application intake wiring** — carry `Application.background` to the new
   Profile field at acceptance.

---

## 1. Background attribute

### Model
Add to `accounts.Profile`:

```python
clinical_background = models.BooleanField(
    default=False,
    help_text="Clinical background requires two control analyses "
              "(one ≥4yr, one ≥2yr); academic requires three "
              "(one ≥4yr, two ≥2yr). Set at acceptance from the "
              "application; adjustable by an advisor or admin.",
)
```

`True` = clinical → **2** required (1×≥4yr + 1×≥2yr).
`False` = academic → **3** required (1×≥4yr + 2×≥2yr).

A helper on `Profile`:

```python
def control_requirement(self) -> dict:
    """{'four_year': 1, 'two_year': 1 or 2} per background."""
```

### Backfill (data migration)
- `role == "analyst"` → `clinical_background = True` (moot for them, but a
  sensible default).
- Everyone else → `False` (covers pre-candidates/candidates defaulting to
  academic, and scholar-track members, which are inherently academic).

### Editability
- **Not** member-editable. Read-only on the member's own Formation tab
  ("You have a clinical background — two control analyses required").
- **Advisor** may edit it on the advisee-detail page
  (`formation/templates/formation/advisee_detail.html`), gated by the existing
  `formation.permissions.can_view_advisee`.
- **Admin** may edit it in the Django `Profile` admin.
- (Future: possibly lock advisor editing. For now advisor + admin both edit.)

---

## 2. Structured requirement + sub-bars

### Model change to `ControlAnalysis`
Add a requirement tag:

```python
class Requirement(models.TextChoices):
    FOUR_YEAR = "four_year", "4-year"
    TWO_YEAR = "two_year", "2-year"

requirement = models.CharField(
    max_length=10, choices=Requirement.choices, default=Requirement.FOUR_YEAR,
)
```

Member-set, **freely re-taggable** (4-year ↔ 2-year is a normal edit). The tag
records which requirement slot the member intends this analysis to satisfy.

### Thresholds — admin-tunable
Replace `FormationSettings.control_years_target` with:

```python
four_year_threshold = models.PositiveSmallIntegerField(default=4)
two_year_threshold = models.PositiveSmallIntegerField(default=2)
```

(A data migration drops the old field. It is only read in views/templates, so
no external dependents.)

### Slot / sub-bar computation
A pure function in `formation` (e.g. `formation/control.py:control_progress(user)`):

- Requirement counts come from `profile.control_requirement()` — one 4-year
  slot, and one or two 2-year slots.
- **Slot fill:** for the 4-year slot, take the **longest** entry tagged
  `four_year`; for each 2-year slot, take the next-longest entries tagged
  `two_year`. Extra entries beyond the slots still count toward the **Total**
  bar but do not occupy a slot.
- A slot is **met** when its filling entry's `duration_years` crosses the
  threshold.
- Returns a structure the template renders directly:

```python
{
  "total_years": float,          # sum of all entries (Total bar)
  "total_target": int,           # 4 + 2*n_two_year
  "four_year": {"entry": ca_or_none, "years": float, "target": 4, "met": bool},
  "two_year": [                  # 1 (clinical) or 2 (academic) items
     {"entry": ca_or_none, "years": float, "target": 2, "met": bool}, ...
  ],
}
```

### Template
On the Formation tab control section
(`formation/templates/formation/_tab_formation.html`):

- Keep the **Total** progress bar (sum vs. `total_target`).
- Add labelled **sub-bars**: "4-year control" and "2-year control" (×1 or ×2),
  each showing its filling entry's name + progress, or "not yet started" when
  empty. A met slot shows a check / "met".
- The entry list shows each entry's `4-year`/`2-year` badge; the add/edit form
  exposes the tag.

Same sub-bar rendering appears read-only on the advisor's advisee-detail page.

---

## 3. Analyst selection

Control-analysis entries reference an analyst by one of two typed sources,
with the display name cached for existing/imported rows:

```python
school_analyst = models.ForeignKey(
    settings.AUTH_USER_MODEL, null=True, blank=True,
    on_delete=models.SET_NULL, related_name="control_analyses_supervised",
)
external_analyst = models.ForeignKey(
    "formation.ExternalControlAnalyst", null=True, blank=True,
    on_delete=models.SET_NULL, related_name="control_analyses",
)
# supervisor_name retained as a cached/display name + legacy fallback.
```

`ControlAnalysisForm`:

- A **dropdown of School Analysts** — `Profile.role == "analyst"`, active,
  `public` — ordered by name. Selecting one sets `school_analyst` and caches
  `supervisor_name`.
- A dropdown option (or second control) for a **previously-approved external
  analyst** belonging to this member.
- A **"Request an external control analyst"** button/link to the request form
  (§4). Until approved, an external analyst is not selectable.
- `save()` keeps `supervisor_name` in sync with whichever source is chosen.

Existing rows keep their `supervisor_name` and simply have both FKs null — no
data loss.

---

## 4. External-control-analyst authorization

### Model — `formation.ExternalControlAnalyst`

```python
class ExternalControlAnalyst(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested — awaiting the Meeting of the Analysts"
        APPROVED = "approved", "Approved"
        DECLINED = "declined", "Not approved"

    member = FK(User, related_name="external_control_requests")
    name = CharField
    email = EmailField(blank=True)
    phone = PhoneNumberField(blank=True)     # django-phonenumber-field, as elsewhere
    description = TextField   # qualifications / why this analyst
    status = CharField(choices, default=REQUESTED, db_index=True)
    requested_at, decided_at, decided_by (FK User, SET_NULL), decision_note
    created_at, updated_at
```

### Member flow
- Request form at `formation/control/external/request/` (name, email, phone,
  description). On submit → `REQUESTED`, notifies the Meeting of the Analysts.
- The member sees their requests + statuses in the control section; an approved
  one becomes selectable for a control-analysis entry.

### Meeting-of-the-Analysts review flow
Mirror the existing Advancement demande review, reusing
`admissions.views._require_review` / `_can_review` (Meeting of Analysts +
staff/superuser):

- Queue view + detail + decide (`approve`/`decline` with a note), under
  `formation/urls.py` (e.g. `formation:external_queue`, `external_detail`,
  `external_decide`).
- **Surface in the Meeting console** (`core/staff/admin/meeting_of_analysts.html`
  via `core.staff.meeting_of_analysts_admin`) with an open-request count,
  alongside the existing open-application / open-advancement counts.
- A decision service `formation/control.py:decide_external(...)` sets status +
  decided_by/at/note and notifies the member.

### Notifications
Follow `formation/notifications.py` conventions (in-app bell + preference-gated
email via `notify(...)`). Add a notification category for external-analyst
review (member → Meeting on request; Meeting → member on decision). Reuse an
existing formation/admissions category if a suitable one exists; otherwise add
`EXTERNAL_CONTROL_ANALYST` in `notifications/categories.py`.

### Manual override (do-not-over-automate)
Register `ExternalControlAnalyst` in Django admin with `Approve` / `Decline`
actions, so staff have a direct escape hatch independent of the Meeting console.

---

## 5. Application intake wiring

The application form **already** captures `Application.background`
(academic/clinical) for the analyst track; the scholar track is inherently
academic (background left blank).

- In `admissions/services.py:accept_application`, after the role change, set:

  ```python
  profile = application.applicant.profile
  profile.clinical_background = (
      application.background == Application.Background.CLINICAL
  )
  profile.save(update_fields=["clinical_background"])
  ```

  Analyst + clinical → `True`; analyst + academic, scholar track, or blank →
  `False`.
- No application-form change is required (the question already exists); confirm
  the analyst-track form surfaces it (it does — `admissions/forms.py`).

---

## Data model summary

| Model | Change |
|---|---|
| `accounts.Profile` | `+ clinical_background: bool`; `+ control_requirement()` |
| `formation.FormationSettings` | `- control_years_target`; `+ four_year_threshold`, `+ two_year_threshold` |
| `formation.ControlAnalysis` | `+ requirement (4-year/2-year)`; `+ school_analyst FK`; `+ external_analyst FK`; keep `supervisor_name` |
| `formation.ExternalControlAnalyst` | **new** — request + Meeting approval lifecycle |

## Migrations
- `accounts`: add `clinical_background` + data-migration backfill (analysts → True).
- `formation`: add `requirement`, `school_analyst`, `external_analyst`;
  `ExternalControlAnalyst`; swap `FormationSettings` threshold fields
  (drop `control_years_target`, add the two thresholds, data-migrate the value).

## Views / URLs (formation)
- Existing `control_add` / `control_edit` / `control_delete` gain the new
  fields (tag + analyst source).
- New: `external_request` (member), `external_queue` / `external_detail` /
  `external_decide` (Meeting review).

## Testing
- `Profile.control_requirement()` per background (2 vs 3).
- Backfill migration: analyst → clinical, others → academic.
- Slot fill / met logic in `control_progress`: longest-per-tag fills slots;
  per-relationship (not cumulative); extras count only toward Total; re-tagging
  moves an entry between slots.
- Control form: School-analyst dropdown restricted to active public analysts;
  saving syncs `supervisor_name`; only approved external analysts selectable.
- External request → REQUESTED, notifies Meeting; approve/decline updates
  status + notifies member; permission gate (non-reviewer 403).
- Meeting console shows the open-request count.
- `accept_application` sets `clinical_background` from `Application.background`
  (clinical analyst → True; academic / scholar → False).

## Out of scope / non-goals
- No non-overlap validation between simultaneous analyses (they may overlap).
- No automatic role advancement from control-analysis completion (advancement
  stays a separate demande decided by the Meeting).
- The 4-year "or four years of ongoing dialogue with an analyst" phrasing in
  current copy is preserved as descriptive help text, not a separate slot.
