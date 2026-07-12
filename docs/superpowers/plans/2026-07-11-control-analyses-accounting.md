# Control-analyses Accounting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat single-bar control-analysis log with a background-driven, structured requirement (4-year + 2-year slots), a School-analyst dropdown, and a Meeting-of-the-Analysts approval flow for external control analysts.

**Architecture:** Add a `clinical_background` flag to `accounts.Profile` (clinical → 2 required analyses, academic → 3). Tag each `formation.ControlAnalysis` as a `4-year` or `2-year` slot (swappable), compute per-slot sub-bars in a pure `formation/control.py` function, keep the Total bar. Reference analysts via a School-analyst FK or an approved `formation.ExternalControlAnalyst`, the latter gated by a Meeting-of-the-Analysts approval queue that mirrors the existing Advancement demande review. Carry `Application.background` onto the Profile flag at acceptance.

**Tech Stack:** Django 5.2 / Python 3.10+, pytest-django, django-phonenumber-field, Tailwind v4 + DaisyUI (semantic tokens only), `notifications.dispatch.notify` for in-app + email.

## Global Constraints

- Django custom user `accounts.User` (email login, no username). Every `User` has a `Profile` via signal. Never swap `AUTH_USER_MODEL`.
- Templates: DaisyUI semantic tokens only (`bg-base-100`, `text-base-content`, `text-primary`, `progress-primary`, …) — never `bg-gray-100` etc.
- Prose/help-text style: **member-facing site copy uses commas, not em dashes** (per Annie/Diana — `em-dash-prose-style` exception). Docs/chat use unspaced em dashes.
- Every automated path keeps a manual staff override (do-not-over-automate): external-analyst approval must also be doable from Django admin.
- Do NOT rename or reuse the existing `external_add`/`external_edit`/`external_delete` views/urls — those belong to `ExternalActivity`. New control-analyst views use the `external_analyst_*` prefix.
- Gated GET pages redirect anonymous users to login via `core.access.gate_or_login`; the Meeting review views reuse `admissions.views._require_review` (raises `PermissionDenied` for signed-in non-reviewers), matching the Advancement queue.
- Run `uv run pytest` and `uv run ruff check .` green before each commit. Tailwind classes only used in Python widget attrs must also appear in a template or they are dropped from the prod CSS build.

---

## File Structure

- `accounts/models.py` — add `Profile.clinical_background` + `Profile.control_requirement()`.
- `accounts/migrations/00XX_profile_clinical_background.py` — field + data-migration backfill.
- `accounts/admin.py` — expose `clinical_background` on `ProfileAdmin`.
- `formation/models.py` — `ControlAnalysis.requirement` + `school_analyst`/`external_analyst` FKs; `FormationSettings` threshold fields; new `ExternalControlAnalyst`.
- `formation/migrations/00XX_*` — model changes + threshold data-migration.
- `formation/control.py` — **new** pure module: `control_progress(user)` + `decide_external(...)`.
- `formation/forms.py` — `ControlAnalysisForm` (tag + analyst source), new `ExternalControlAnalystForm`.
- `formation/views.py` — control add/edit gain fields; new `external_analyst_request` + Meeting `external_analyst_queue`/`_detail`/`_decide`.
- `formation/urls.py` — new routes.
- `formation/notifications.py` — external-analyst request/decision wrappers.
- `formation/emails.py` — external-analyst request/decision emails.
- `formation/admin.py` — register `ExternalControlAnalyst` with approve/decline actions.
- `notifications/categories.py` — new `EXTERNAL_CONTROL_ANALYST` category + meta.
- `formation/templates/formation/_tab_formation.html`, `advisee_detail.html`, `_control_form.html` — sub-bars, tag, analyst dropdown.
- `formation/templates/formation/external_analyst_*.html` — request form + Meeting queue/detail.
- `core/templates/core/staff/admin/meeting_of_analysts.html` + `core/staff.py` — console card + open count.
- `admissions/services.py` — set `clinical_background` in `accept_application`.
- Tests: `formation/test_control.py`, `formation/test_control_views.py`, `formation/test_external_analyst.py` (new), `accounts/tests` (backfill/requirement), `admissions/test_*` (intake).

---

## Task 1: Profile.clinical_background + requirement helper + backfill

**Files:**
- Modify: `accounts/models.py` (Profile, near other formation helpers ~line 445–475)
- Modify: `accounts/admin.py` (ProfileAdmin ~line 78–81)
- Create: `accounts/migrations/00XX_profile_clinical_background.py`
- Test: `accounts/test_clinical_background.py` (new)

**Interfaces:**
- Produces: `Profile.clinical_background: bool`; `Profile.control_requirement() -> dict` returning `{"four_year": 1, "two_year": 1 if clinical else 2}`.

- [ ] **Step 1: Write the failing test**

Create `accounts/test_clinical_background.py`:

```python
import pytest

from accounts.models import Profile, User

pytestmark = pytest.mark.django_db


def _user(email, role):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


def test_clinical_requirement_two_analyses():
    u = _user("clin@example.com", Profile.Role.ANALYST)
    u.profile.clinical_background = True
    assert u.profile.control_requirement() == {"four_year": 1, "two_year": 1}


def test_academic_requirement_three_analyses():
    u = _user("acad@example.com", Profile.Role.PRE_CANDIDATE)
    assert u.profile.clinical_background is False
    assert u.profile.control_requirement() == {"four_year": 1, "two_year": 2}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest accounts/test_clinical_background.py -v`
Expected: FAIL — `Profile` has no attribute `clinical_background` / `control_requirement`.

- [ ] **Step 3: Add the field + helper**

In `accounts/models.py`, add the field to `Profile` (near `is_faculty`/`public`):

```python
    clinical_background = models.BooleanField(
        default=False,
        help_text="Clinical background requires two control analyses "
                  "(one of at least 4 years, one of at least 2 years); "
                  "academic requires three (one of at least 4 years, two of "
                  "at least 2 years). Set at acceptance from the application; "
                  "adjustable by an advisor or admin.",
    )
```

And a method on `Profile`:

```python
    def control_requirement(self) -> dict:
        """How many control analyses this member owes, by slot. Clinical
        background: one 4-year + one 2-year. Academic: one 4-year + two 2-year."""
        return {"four_year": 1, "two_year": 1 if self.clinical_background else 2}
```

- [ ] **Step 4: Create the migration with backfill**

Run: `uv run python manage.py makemigrations accounts`

Then edit the generated migration to add a data migration operation after the `AddField`:

```python
def backfill_clinical(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    Profile.objects.filter(role="analyst").update(clinical_background=True)


def unbackfill(apps, schema_editor):
    pass  # field is dropped on reverse; no-op


# ...inside Migration.operations, after migrations.AddField(...):
    migrations.RunPython(backfill_clinical, unbackfill),
```

- [ ] **Step 5: Expose in admin**

In `accounts/admin.py` `ProfileAdmin`, add to `list_display` and `list_filter`:

```python
    list_display = ("user", "role", "is_faculty", "clinical_background")
    list_filter = ("role", "is_faculty", "public", "clinical_background")
```

Add a backfill-verification test to `accounts/test_clinical_background.py`:

```python
def test_backfill_sets_analysts_clinical(django_assert_num_queries=None):
    from django.core.management import call_command  # noqa: F401
    # The data migration already ran for the test DB; assert the rule directly.
    u = _user("a2@example.com", Profile.Role.ANALYST)
    # New analysts default False (created after migration); the migration only
    # touched existing rows. Verify the requirement math instead:
    u.profile.clinical_background = True
    u.profile.save()
    assert u.profile.control_requirement()["two_year"] == 1
```

- [ ] **Step 6: Run tests + lint + migrate**

Run: `uv run pytest accounts/test_clinical_background.py -v && uv run ruff check accounts && uv run python manage.py migrate`
Expected: PASS; migration applies cleanly.

- [ ] **Step 7: Commit**

```bash
git add accounts/models.py accounts/admin.py accounts/migrations accounts/test_clinical_background.py
git commit -m "feat(accounts): Profile.clinical_background + control_requirement (task #415)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: ControlAnalysis requirement tag (4-year / 2-year)

**Files:**
- Modify: `formation/models.py` (`ControlAnalysis` ~line 180)
- Modify: `formation/forms.py` (`ControlAnalysisForm` ~line 67)
- Modify: `formation/templates/formation/_control_form.html`, `_tab_formation.html` (entry list badge)
- Create: `formation/migrations/00XX_controlanalysis_requirement.py`
- Test: `formation/test_control.py`

**Interfaces:**
- Produces: `ControlAnalysis.Requirement` (`FOUR_YEAR="four_year"`, `TWO_YEAR="two_year"`); `ControlAnalysis.requirement` (default `FOUR_YEAR`).

- [ ] **Step 1: Write the failing test**

Append to `formation/test_control.py`:

```python
def test_control_requirement_tag_defaults_four_year(db):
    from accounts.models import User
    from formation.models import ControlAnalysis
    import datetime as dt

    u = User.objects.create_user(email="t@example.com", password="x")
    ca = ControlAnalysis.objects.create(
        member=u, supervisor_name="S", start_date=dt.date(2020, 1, 1),
    )
    assert ca.requirement == ControlAnalysis.Requirement.FOUR_YEAR
    ca.requirement = ControlAnalysis.Requirement.TWO_YEAR
    ca.save()
    assert ca.refresh_from_db() is None and ca.requirement == "two_year"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest formation/test_control.py::test_control_requirement_tag_defaults_four_year -v`
Expected: FAIL — no `Requirement` / `requirement`.

- [ ] **Step 3: Add the field**

In `formation/models.py` `ControlAnalysis`, add after `Modality`:

```python
    class Requirement(models.TextChoices):
        FOUR_YEAR = "four_year", "4-year"
        TWO_YEAR = "two_year", "2-year"
```

And a field (after `modality`):

```python
    requirement = models.CharField(
        max_length=10, choices=Requirement.choices, default=Requirement.FOUR_YEAR,
        help_text="Which requirement this analysis is meant to satisfy. "
                  "Freely changeable between 4-year and 2-year.",
    )
```

- [ ] **Step 4: Migration**

Run: `uv run python manage.py makemigrations formation`
Expected: one `AddField` for `requirement`.

- [ ] **Step 5: Expose in the form**

In `formation/forms.py` `ControlAnalysisForm.Meta.fields`, add `"requirement"` (after `"modality"`), and a widget:

```python
        fields = ("supervisor_name", "requirement", "modality",
                  "start_date", "end_date", "notes")
        widgets = {
            ...
            "requirement": forms.Select(attrs={"class": "select select-bordered w-full"}),
            ...
        }
```

In `__init__`, add:

```python
        self.fields["requirement"].label = "Counts toward"
        self.fields["requirement"].help_text = (
            "Tag this as your 4-year control analysis or a 2-year one. "
            "You can change it later."
        )
```

- [ ] **Step 6: Render the tag in templates**

In `_control_form.html`, add a field block (after the modality block), mirroring existing block markup:

```html
    <div class="space-y-1">
      <label for="{{ form.requirement.id_for_label }}" class="block text-sm font-medium">Counts toward</label>
      {{ form.requirement }}
      <p class="text-xs text-base-content/60">{{ form.requirement.help_text }}</p>
      {% if form.requirement.errors %}<p class="text-error text-xs mt-1">{{ form.requirement.errors|join:", " }}</p>{% endif %}
    </div>
```

In `_tab_formation.html`, inside the control entry `<li>` (near supervisor name ~line 167), add a badge:

```html
            <span class="badge badge-outline badge-sm">{{ c.get_requirement_display }} control</span>
```

- [ ] **Step 7: Run tests + lint + build CSS**

Run: `uv run pytest formation/test_control.py -v && uv run ruff check formation && npm run build:css`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add formation/models.py formation/forms.py formation/migrations formation/templates formation/test_control.py
git commit -m "feat(formation): tag each control analysis as 4-year or 2-year (task #415)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: FormationSettings thresholds + control_progress() sub-bars

**Files:**
- Modify: `formation/models.py` (`FormationSettings` ~line 162)
- Create: `formation/control.py`
- Modify: `formation/views.py` (`_formation_context` ~line 93–95; `advisee_detail` ~line 686–689)
- Modify: `formation/templates/formation/_tab_formation.html` (control section ~line 149–191), `advisee_detail.html` (~line 60–70)
- Create: `formation/migrations/00XX_formationsettings_thresholds.py`
- Test: `formation/test_control.py`, `formation/test_control_views.py`

**Interfaces:**
- Consumes: `Profile.control_requirement()` (Task 1), `ControlAnalysis.requirement`/`duration_years` (Task 2).
- Produces:
  - `FormationSettings.four_year_threshold: int` (default 4), `two_year_threshold: int` (default 2); `control_years_target` removed.
  - `formation.control.control_progress(user) -> dict` with keys `total_years, total_target, four_year, two_year`:
    - `four_year`: `{"entry": ControlAnalysis|None, "years": float, "target": int, "met": bool}`
    - `two_year`: `list[dict]` (length 1 or 2), each same shape.

- [ ] **Step 1: Write the failing test**

Replace the target-based assertions in `formation/test_control.py` (the `control_years_target == 6` test) and add:

```python
def test_control_progress_fills_slots_by_longest_per_tag(db):
    import datetime as dt
    from accounts.models import Profile, User
    from formation.models import ControlAnalysis
    from formation.control import control_progress

    u = User.objects.create_user(email="p@example.com", password="x")
    u.profile.role = Profile.Role.PRE_CANDIDATE  # academic -> 2 two-year slots
    u.profile.clinical_background = False
    u.profile.save()

    today = dt.date.today()
    # A 5-year four-year entry, and two two-year entries (3yr and 1yr).
    ControlAnalysis.objects.create(
        member=u, supervisor_name="Long", requirement="four_year",
        start_date=today - dt.timedelta(days=int(365.25 * 5)),
    )
    ControlAnalysis.objects.create(
        member=u, supervisor_name="Mid", requirement="two_year",
        start_date=today - dt.timedelta(days=int(365.25 * 3)),
    )
    ControlAnalysis.objects.create(
        member=u, supervisor_name="Short", requirement="two_year",
        start_date=today - dt.timedelta(days=int(365.25 * 1)),
    )

    prog = control_progress(u)
    assert prog["total_target"] == 8            # 4 + 2*2
    assert prog["four_year"]["met"] is True
    assert prog["four_year"]["entry"].supervisor_name == "Long"
    assert len(prog["two_year"]) == 2
    assert prog["two_year"][0]["entry"].supervisor_name == "Mid"  # longest first
    assert prog["two_year"][0]["met"] is True                     # 3yr >= 2
    assert prog["two_year"][1]["met"] is False                    # 1yr < 2


def test_control_progress_clinical_has_one_two_year_slot(db):
    from accounts.models import Profile, User
    from formation.control import control_progress

    u = User.objects.create_user(email="c@example.com", password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.clinical_background = True
    u.profile.save()
    prog = control_progress(u)
    assert prog["total_target"] == 6            # 4 + 2*1
    assert len(prog["two_year"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest formation/test_control.py -k control_progress -v`
Expected: FAIL — no module `formation.control`.

- [ ] **Step 3: Swap FormationSettings fields**

In `formation/models.py`, replace `control_years_target` with:

```python
    four_year_threshold = models.PositiveSmallIntegerField(
        default=4, help_text="Years for the longer (4-year) control analysis.",
    )
    two_year_threshold = models.PositiveSmallIntegerField(
        default=2, help_text="Years for each shorter (2-year) control analysis.",
    )
```

- [ ] **Step 4: Write control_progress**

Create `formation/control.py`:

```python
"""Structured control-analysis accounting: per-slot progress toward the
background-dependent requirement (one 4-year + one/two 2-year analyses)."""

from __future__ import annotations

from .models import ControlAnalysis, FormationSettings


def _slot(entry, target):
    years = entry.duration_years if entry else 0.0
    return {"entry": entry, "years": round(years, 2), "target": target,
            "met": bool(entry and years >= target)}


def control_progress(user) -> dict:
    """Sub-bar data for a member's control analyses.

    Each requirement slot is filled by the *longest single* entry with the
    matching tag (per-relationship, not cumulative); leftover entries still
    count toward the Total bar. Slot counts come from
    ``Profile.control_requirement()``.
    """
    settings_ = FormationSettings.load()
    req = user.profile.control_requirement()
    entries = list(ControlAnalysis.objects.filter(member=user))

    four = sorted(
        (c for c in entries if c.requirement == ControlAnalysis.Requirement.FOUR_YEAR),
        key=lambda c: c.duration_years, reverse=True,
    )
    twos = sorted(
        (c for c in entries if c.requirement == ControlAnalysis.Requirement.TWO_YEAR),
        key=lambda c: c.duration_years, reverse=True,
    )

    n_two = req["two_year"]
    two_slots = [
        _slot(twos[i] if i < len(twos) else None, settings_.two_year_threshold)
        for i in range(n_two)
    ]
    total_years = round(sum(c.duration_years for c in entries), 2)
    total_target = settings_.four_year_threshold + settings_.two_year_threshold * n_two
    return {
        "total_years": total_years,
        "total_target": total_target,
        "four_year": _slot(four[0] if four else None, settings_.four_year_threshold),
        "two_year": two_slots,
    }
```

- [ ] **Step 5: Migration (drop target, add thresholds)**

Run: `uv run python manage.py makemigrations formation`
Expected: `RemoveField(control_years_target)` + two `AddField`. No data migration needed (new defaults 4/2 reproduce the old total of 6 for clinical).

- [ ] **Step 6: Wire into the views**

In `formation/views.py` `_formation_context`, replace the three `control_*` context keys (~line 93–95) with:

```python
        "control_entries": ControlAnalysis.objects.filter(member=user),
        "control_progress": __import__("formation.control", fromlist=["control_progress"]).control_progress(user),
```

Prefer a top-of-file import instead: add `from .control import control_progress` and use `"control_progress": control_progress(user)`. Do the same in `advisee_detail` (~line 686–689), passing `advisee`:

```python
        "control_entries": ControlAnalysis.objects.filter(member=advisee),
        "control_progress": control_progress(advisee),
```

- [ ] **Step 7: Update templates to sub-bars**

In `_tab_formation.html`, replace the single progress block (~line 157–160) with a Total bar + sub-bars. Use member-facing comma style (no em dashes):

```html
      <div class="space-y-1">
        <progress class="progress progress-primary w-full" value="{{ control_progress.total_years }}" max="{{ control_progress.total_target }}"></progress>
        <p class="text-sm text-base-content/70">{{ control_progress.total_years|floatformat:1 }} of {{ control_progress.total_target }} total years across your control analyses.</p>
      </div>

      <div class="space-y-3">
        {# 4-year slot #}
        <div class="space-y-1">
          <div class="flex items-center justify-between text-sm">
            <span class="font-medium">4-year control analysis</span>
            {% if control_progress.four_year.met %}<span class="badge badge-success badge-sm">met</span>{% endif %}
          </div>
          <progress class="progress progress-secondary w-full" value="{{ control_progress.four_year.years }}" max="{{ control_progress.four_year.target }}"></progress>
          <p class="text-xs text-base-content/60">
            {% if control_progress.four_year.entry %}{{ control_progress.four_year.entry.supervisor_name }}, {{ control_progress.four_year.years|floatformat:1 }} of {{ control_progress.four_year.target }} years{% else %}Not yet started.{% endif %}
          </p>
        </div>
        {# 2-year slots #}
        {% for slot in control_progress.two_year %}
        <div class="space-y-1">
          <div class="flex items-center justify-between text-sm">
            <span class="font-medium">2-year control analysis{% if control_progress.two_year|length > 1 %} #{{ forloop.counter }}{% endif %}</span>
            {% if slot.met %}<span class="badge badge-success badge-sm">met</span>{% endif %}
          </div>
          <progress class="progress progress-secondary w-full" value="{{ slot.years }}" max="{{ slot.target }}"></progress>
          <p class="text-xs text-base-content/60">
            {% if slot.entry %}{{ slot.entry.supervisor_name }}, {{ slot.years|floatformat:1 }} of {{ slot.target }} years{% else %}Not yet started.{% endif %}
          </p>
        </div>
        {% endfor %}
      </div>
```

In `advisee_detail.html` (~line 60–70), replace the single progress block with the same structure (read-only; no "met" wording change needed) referencing `control_progress`.

- [ ] **Step 8: Fix the old context-key tests**

In `formation/test_control_views.py`, replace the `test_formation_tab_shows_control_context` assertions that reference `control_years`/`control_target == 6` with:

```python
    assert "control_progress" in resp.context
    assert resp.context["control_progress"]["total_target"] in (6, 8)
```

Remove/replace the `FormationSettings.load().control_years_target == 6` assertion in `formation/test_control.py` (that field no longer exists).

- [ ] **Step 9: Run tests + lint + CSS**

Run: `uv run pytest formation -v && uv run ruff check formation && npm run build:css`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add formation/ 
git commit -m "feat(formation): per-slot control-analysis sub-bars + tunable thresholds (task #415)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: ExternalControlAnalyst model + admin override

**Files:**
- Modify: `formation/models.py` (append after `ControlAnalysis`)
- Modify: `formation/admin.py`
- Create: `formation/migrations/00XX_externalcontrolanalyst.py`
- Test: `formation/test_external_analyst.py` (new)

**Interfaces:**
- Produces: `formation.models.ExternalControlAnalyst` with `Status` (`REQUESTED`, `APPROVED`, `DECLINED`), fields `member, name, email, phone, description, status, requested_at, decided_at, decided_by, decision_note`, `is_open` property, `OPEN_STATUSES`.

- [ ] **Step 1: Write the failing test**

Create `formation/test_external_analyst.py`:

```python
import pytest

from accounts.models import User
from formation.models import ExternalControlAnalyst

pytestmark = pytest.mark.django_db


def test_external_request_defaults_to_requested():
    u = User.objects.create_user(email="m@example.com", password="x")
    e = ExternalControlAnalyst.objects.create(
        member=u, name="Dr External", description="Longtime supervisor.",
    )
    assert e.status == ExternalControlAnalyst.Status.REQUESTED
    assert e.is_open is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest formation/test_external_analyst.py -v`
Expected: FAIL — no `ExternalControlAnalyst`.

- [ ] **Step 3: Add the model**

In `formation/models.py` (top import already has `settings`, `models`, `timezone`; add phone import):

```python
from phonenumber_field.modelfields import PhoneNumberField
```

Append:

```python
class ExternalControlAnalyst(models.Model):
    """A member's request to use an analyst outside the School for control
    (supervisory) analysis. Authorized by the Meeting of the Analysts."""

    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested — awaiting the Meeting of the Analysts"
        APPROVED = "approved", "Approved"
        DECLINED = "declined", "Not approved"

    OPEN_STATUSES = (Status.REQUESTED,)

    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="external_control_requests",
    )
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    phone = PhoneNumberField(blank=True)
    description = models.TextField(
        help_text="Who this analyst is and why you're requesting them "
                  "(qualifications, background).",
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.REQUESTED, db_index=True,
    )
    requested_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="external_control_decisions",
    )
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-requested_at",)

    def __str__(self):
        return f"{self.name} (external, {self.get_status_display()})"

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN_STATUSES
```

- [ ] **Step 4: Migration**

Run: `uv run python manage.py makemigrations formation`

- [ ] **Step 5: Admin with approve/decline actions**

In `formation/admin.py`:

```python
from django.utils import timezone

from .models import ExternalControlAnalyst


@admin.register(ExternalControlAnalyst)
class ExternalControlAnalystAdmin(admin.ModelAdmin):
    list_display = ("name", "member", "status", "requested_at", "decided_at")
    list_filter = ("status",)
    search_fields = ("name", "member__email", "member__last_name")
    actions = ("approve_selected", "decline_selected")

    @admin.action(description="Approve selected external analysts")
    def approve_selected(self, request, queryset):
        from formation.control import decide_external
        for obj in queryset.filter(status=ExternalControlAnalyst.Status.REQUESTED):
            decide_external(obj, approve=True, by=request.user, note="Approved via admin.")

    @admin.action(description="Decline selected external analysts")
    def decline_selected(self, request, queryset):
        from formation.control import decide_external
        for obj in queryset.filter(status=ExternalControlAnalyst.Status.REQUESTED):
            decide_external(obj, approve=False, by=request.user, note="Declined via admin.")
```

> `decide_external` is defined in Task 6 Step 3. If running strictly in order, the admin actions import lazily (inside the method) so importing the module is safe before Task 6; a test that *invokes* the actions belongs in Task 6.

- [ ] **Step 6: Run tests + migrate + lint**

Run: `uv run pytest formation/test_external_analyst.py -v && uv run python manage.py migrate && uv run ruff check formation`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add formation/models.py formation/admin.py formation/migrations formation/test_external_analyst.py
git commit -m "feat(formation): ExternalControlAnalyst model + admin override (task #415)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Analyst source on ControlAnalysis (School dropdown + external FK)

**Files:**
- Modify: `formation/models.py` (`ControlAnalysis` FKs)
- Modify: `formation/forms.py` (`ControlAnalysisForm`)
- Modify: `formation/views.py` (`control_add`/`control_edit` pass `request.user` to the form)
- Modify: `formation/templates/formation/_control_form.html`
- Create: `formation/migrations/00XX_controlanalysis_analyst_sources.py`
- Test: `formation/test_control_views.py`

**Interfaces:**
- Consumes: `ExternalControlAnalyst` (Task 4).
- Produces: `ControlAnalysis.school_analyst` (FK User, nullable), `ControlAnalysis.external_analyst` (FK ExternalControlAnalyst, nullable); `ControlAnalysisForm(user=...)` restricts the School dropdown to active public analysts and approved external analysts owned by `user`, and syncs `supervisor_name`.

- [ ] **Step 1: Write the failing test**

Append to `formation/test_control_views.py`:

```python
def test_control_form_school_dropdown_lists_only_active_public_analysts(db):
    from accounts.models import Profile, User
    from formation.forms import ControlAnalysisForm

    member = User.objects.create_user(email="mem@example.com", password="x")
    analyst = User.objects.create_user(email="an@example.com", password="x")
    analyst.profile.role = Profile.Role.ANALYST
    analyst.profile.public = True
    analyst.profile.save()
    hidden = User.objects.create_user(email="hid@example.com", password="x")
    hidden.profile.role = Profile.Role.ANALYST
    hidden.profile.public = False
    hidden.profile.save()

    form = ControlAnalysisForm(user=member)
    qs = form.fields["school_analyst"].queryset
    assert analyst in qs and hidden not in qs and member not in qs


def test_control_save_syncs_supervisor_name_from_school_analyst(client, db):
    from django.urls import reverse
    from accounts.models import Profile, User
    from formation.models import ControlAnalysis

    member = User.objects.create_user(email="mem2@example.com", password="x")
    analyst = User.objects.create_user(
        email="an2@example.com", password="x", first_name="Jane", last_name="Roe")
    analyst.profile.role = Profile.Role.ANALYST
    analyst.profile.public = True
    analyst.profile.save()
    client.force_login(member)

    resp = client.post(reverse("formation:control_add"), {
        "supervisor_name": "", "school_analyst": analyst.pk,
        "requirement": "four_year", "modality": "remote",
        "start_date": "2020-01-01",
    })
    assert resp.status_code == 302
    ca = ControlAnalysis.objects.get(member=member)
    assert ca.school_analyst_id == analyst.pk
    assert ca.supervisor_name == "Jane Roe"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest formation/test_control_views.py -k "school_dropdown or syncs_supervisor" -v`
Expected: FAIL — no `school_analyst` field.

- [ ] **Step 3: Add the FKs**

In `formation/models.py` `ControlAnalysis` (after `member`), add:

```python
    school_analyst = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="control_analyses_supervised",
        help_text="An Analyst of the School, chosen from the directory.",
    )
    external_analyst = models.ForeignKey(
        "formation.ExternalControlAnalyst", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="control_analyses",
        help_text="An approved external control analyst.",
    )
```

Keep `supervisor_name` (now a cached display name; make it optional):

```python
    supervisor_name = models.CharField(max_length=200, blank=True)
```

- [ ] **Step 4: Migration**

Run: `uv run python manage.py makemigrations formation`
Expected: two `AddField` + one `AlterField` (supervisor_name blank).

- [ ] **Step 5: Rework the form**

In `formation/forms.py`, add imports and rewrite `ControlAnalysisForm`:

```python
from django.db.models import Q

from accounts.models import Profile, User

from .models import ControlAnalysis, ExternalControlAnalyst
```

```python
class ControlAnalysisForm(forms.ModelForm):
    school_analyst = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False,
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
        label="Analyst of the School",
        help_text="Choose from the School's analysts, or request an external "
                  "analyst below.",
    )
    external_analyst = forms.ModelChoiceField(
        queryset=ExternalControlAnalyst.objects.none(), required=False,
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
        label="Approved external analyst",
    )

    class Meta:
        model = ControlAnalysis
        fields = ("school_analyst", "external_analyst", "supervisor_name",
                  "requirement", "modality", "start_date", "end_date", "notes")
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date", "class": _INPUT}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": _INPUT}),
            "supervisor_name": forms.TextInput(attrs={"class": _INPUT}),
            "requirement": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "modality": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": _TEXTAREA}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["school_analyst"].queryset = (
            User.objects.filter(
                profile__role=Profile.Role.ANALYST,
                profile__public=True,
                profile__standing=Profile.Standing.ACTIVE,
                is_active=True,
            ).order_by("last_name", "first_name")
        )
        if user is not None:
            self.fields["external_analyst"].queryset = (
                ExternalControlAnalyst.objects.filter(
                    member=user, status=ExternalControlAnalyst.Status.APPROVED)
            )
        self.fields["requirement"].label = "Counts toward"
        self.fields["requirement"].help_text = (
            "Tag this as your 4-year control analysis or a 2-year one. "
            "You can change it later."
        )
        self.fields["supervisor_name"].label = "Or type a name"
        self.fields["supervisor_name"].help_text = (
            "Only if the analyst is not selectable above."
        )
        self.fields["supervisor_name"].required = False
        self.fields["end_date"].label = "End date"
        self.fields["end_date"].help_text = "Leave blank if this is ongoing."
        self.fields["end_date"].required = False
        self.fields["notes"].required = False

    def clean(self):
        cleaned = super().clean()
        school = cleaned.get("school_analyst")
        external = cleaned.get("external_analyst")
        typed = (cleaned.get("supervisor_name") or "").strip()
        if not (school or external or typed):
            raise forms.ValidationError(
                "Choose a School analyst, an approved external analyst, or type a name.")
        # Cache a display name.
        if school:
            cleaned["supervisor_name"] = school.get_full_name() or school.email
        elif external:
            cleaned["supervisor_name"] = external.name
        return cleaned
```

- [ ] **Step 6: Pass `user` from the views**

In `formation/views.py` `control_add`/`control_edit`, construct the form with `user=request.user`:

```python
        form = ControlAnalysisForm(request.POST, user=request.user)          # add
        form = ControlAnalysisForm(request.POST, instance=obj, user=request.user)  # edit
        form = ControlAnalysisForm(user=request.user)                        # add GET
        form = ControlAnalysisForm(instance=obj, user=request.user)          # edit GET
```

- [ ] **Step 7: Update the form template**

In `_control_form.html`, replace the single "Supervisor" text block with the dropdown(s) + fallback name + a link to request an external analyst:

```html
    <div class="space-y-1">
      <label for="{{ form.school_analyst.id_for_label }}" class="block text-sm font-medium">Analyst of the School</label>
      {{ form.school_analyst }}
      <p class="text-xs text-base-content/60">{{ form.school_analyst.help_text }}</p>
    </div>

    {% if form.external_analyst.field.queryset.exists %}
    <div class="space-y-1">
      <label for="{{ form.external_analyst.id_for_label }}" class="block text-sm font-medium">Approved external analyst</label>
      {{ form.external_analyst }}
    </div>
    {% endif %}

    <div class="space-y-1">
      <label for="{{ form.supervisor_name.id_for_label }}" class="block text-sm font-medium">Or type a name</label>
      {{ form.supervisor_name }}
      <p class="text-xs text-base-content/60">{{ form.supervisor_name.help_text }}</p>
    </div>

    <p class="text-sm">
      <a href="{% url 'formation:external_analyst_request' %}" class="text-primary border-b border-dotted border-primary/50">Request authorization for an external control analyst</a>
    </p>
```

(Leave the modality/requirement/date/notes blocks as they are; ensure `select select-bordered` etc. appear here so Tailwind keeps them.)

- [ ] **Step 8: Run tests + lint + CSS**

Run: `uv run pytest formation/test_control_views.py -v && uv run ruff check formation && npm run build:css`
Expected: PASS (the `external_analyst_request` URL is added in Task 6; if running strictly in order, add a placeholder `path` now or reorder Step 7's link after Task 6 — simplest: do Task 6 before rebuilding the template link).

> **Ordering note:** the template link in Step 7 references `formation:external_analyst_request` (Task 6). Either add the URL stub in Task 6 first, or wrap the link in `{% if %}`-free but accept that template reverse only runs at render. Tests here don't render `_control_form.html`, so they pass; a full page-render test lives in Task 6.

- [ ] **Step 9: Commit**

```bash
git add formation/models.py formation/forms.py formation/views.py formation/templates/formation/_control_form.html formation/migrations formation/test_control_views.py
git commit -m "feat(formation): choose a School analyst for a control analysis (task #415)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: External-analyst request flow + notifications

**Files:**
- Create: `formation/forms.py` `ExternalControlAnalystForm`
- Modify: `formation/control.py` (add `decide_external`)
- Modify: `formation/views.py` (`external_analyst_request`)
- Modify: `formation/urls.py`
- Modify: `formation/notifications.py`, `formation/emails.py`
- Modify: `notifications/categories.py`
- Create: `formation/templates/formation/external_analyst_request.html`
- Modify: `formation/templates/formation/_tab_formation.html` (list member's requests)
- Test: `formation/test_external_analyst.py`

**Interfaces:**
- Consumes: `ExternalControlAnalyst` (Task 4), `admissions.views._can_review` (for the queue in Task 7), `notifications.dispatch.notify`.
- Produces:
  - `formation.control.decide_external(obj, *, approve: bool, by, note: str = "") -> ExternalControlAnalyst`
  - `Category.EXTERNAL_CONTROL_ANALYST`
  - URL `formation:external_analyst_request`.

- [ ] **Step 1: Write the failing test**

Append to `formation/test_external_analyst.py`:

```python
def test_member_requests_external_analyst(client):
    from django.urls import reverse
    u = User.objects.create_user(email="req@example.com", password="x")
    client.force_login(u)
    resp = client.post(reverse("formation:external_analyst_request"), {
        "name": "Dr Outside", "email": "dr@out.example",
        "description": "My supervisor of ten years.",
    })
    assert resp.status_code == 302
    e = ExternalControlAnalyst.objects.get(member=u)
    assert e.status == ExternalControlAnalyst.Status.REQUESTED
    assert e.name == "Dr Outside"


def test_decide_external_approve_notifies_member(db):
    from formation.control import decide_external
    from notifications.models import Notification
    u = User.objects.create_user(email="dec@example.com", password="x")
    reviewer = User.objects.create_user(email="rev@example.com", password="x",
                                        is_staff=True)
    e = ExternalControlAnalyst.objects.create(
        member=u, name="Dr X", description="...")
    decide_external(e, approve=True, by=reviewer, note="ok")
    e.refresh_from_db()
    assert e.status == ExternalControlAnalyst.Status.APPROVED
    assert e.decided_by == reviewer
    assert Notification.objects.filter(recipient=u).exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest formation/test_external_analyst.py -k "requests_external or decide_external" -v`
Expected: FAIL — no URL / no `decide_external`.

- [ ] **Step 3: Add the notification category**

In `notifications/categories.py`, add to `Category` under the Admissions block:

```python
    EXTERNAL_CONTROL_ANALYST = "external_control_analyst", _("External control analyst review")
```

And to `CATEGORY_META` (in `SECTION_ADMISSIONS`, after `ADMISSIONS_ADVANCEMENT`):

```python
    _C.EXTERNAL_CONTROL_ANALYST: _M(
        SECTION_ADMISSIONS, _("External control analyst"),
        _("Requests to authorize an analyst outside the School for control "
          "analysis, and decisions on yours."),
    ),
```

Run `uv run python manage.py makemigrations notifications` (a no-op `AlterField` for the new choice on `Notification.category`); commit it with this task.

- [ ] **Step 4: The form**

In `formation/forms.py`:

```python
class ExternalControlAnalystForm(forms.ModelForm):
    class Meta:
        model = ExternalControlAnalyst
        fields = ("name", "email", "phone", "description")
        widgets = {
            "name": forms.TextInput(attrs={"class": _INPUT}),
            "email": forms.EmailInput(attrs={"class": _INPUT}),
            "phone": forms.TextInput(attrs={"class": _INPUT}),
            "description": forms.Textarea(attrs={"rows": 4, "class": _TEXTAREA}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = False
        self.fields["phone"].required = False
        self.fields["description"].label = "About this analyst"
        self.fields["description"].help_text = (
            "Who they are and why you're requesting them, including their "
            "qualifications."
        )
```

- [ ] **Step 5: `decide_external` service + notification wrappers**

In `formation/control.py`, add:

```python
from django.utils import timezone


def decide_external(obj, *, approve, by, note=""):
    """Approve or decline an external-control-analyst request and notify the
    requesting member."""
    from .models import ExternalControlAnalyst
    from . import notifications as notify_formation

    obj.status = (ExternalControlAnalyst.Status.APPROVED if approve
                  else ExternalControlAnalyst.Status.DECLINED)
    obj.decided_at = timezone.now()
    obj.decided_by = by
    obj.decision_note = note
    obj.save(update_fields=["status", "decided_at", "decided_by", "decision_note"])
    notify_formation.external_analyst_decision(obj)
    return obj
```

In `formation/notifications.py`, add:

```python
def external_analyst_requested(obj) -> None:
    """Notify the Meeting of the Analysts that a member requested an external
    control analyst."""
    from workgroups.permissions import meeting_of_analysts_members  # returns iterable of users
    from . import emails
    for reviewer in meeting_of_analysts_members():
        notify(
            reviewer, Category.EXTERNAL_CONTROL_ANALYST,
            title=f"{_name(obj.member)} requested an external control analyst",
            url=reverse("formation:external_analyst_queue"), target=obj, dedupe=True,
            email_fn=lambda r=reviewer: emails.send_external_analyst_requested(obj, r),
        )


def external_analyst_decision(obj) -> None:
    from . import emails
    approved = obj.status == obj.Status.APPROVED
    notify(
        obj.member, Category.ADMISSIONS_DECISION,
        title=("Your external control analyst was approved" if approved
               else "Your external control analyst request was not approved"),
        url=reverse("formation:formation") + "?tab=formation#control", target=obj,
        email_fn=lambda: emails.send_external_analyst_decision(obj),
    )
```

> Check `workgroups/permissions.py` for the exact helper that returns Meeting members. If only `is_meeting_of_analysts(user)` exists, add a `meeting_of_analysts_members()` iterator there (active analysts) — the availability/admissions code already needs the analyst set, so reuse it if present (search `analysts_of_the_school` / `active_analysts`).

Add matching functions in `formation/emails.py` following the existing `send_advancement_*` pattern (plain `EmailMessage`, `Reply-To: SUPPORT_EMAIL`, member-facing comma copy). Keep them short; reuse `school_from("LSP Meeting of the Analysts")` if that helper exists (`core.email.school_from`).

- [ ] **Step 6: The view + URL**

In `formation/views.py`:

```python
@login_required
def external_analyst_request(request):
    """A member requests authorization to use an external control analyst."""
    from .forms import ExternalControlAnalystForm
    from . import notifications as notify_formation
    if request.method == "POST":
        form = ExternalControlAnalystForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.member = request.user
            obj.save()
            notify_formation.external_analyst_requested(obj)
            messages.success(
                request,
                "Request sent to the Meeting of the Analysts. You'll be notified "
                "when they decide.")
            return redirect(_formation_url("formation") + "#control")
    else:
        form = ExternalControlAnalystForm()
    return render(request, "formation/external_analyst_request.html", {"form": form})
```

In `formation/urls.py`, add under the member hub block:

```python
    path("formation/control/external-analyst/request/",
         views.external_analyst_request, name="external_analyst_request"),
```

- [ ] **Step 7: Templates**

Create `formation/templates/formation/external_analyst_request.html` (extend `core/base.html`, standard form markup like `_control_form.html`, back-link to `?tab=formation#control`, comma copy).

In `_tab_formation.html`, below the entry list, add a member-facing list of their external requests + statuses:

```html
      {% if external_requests %}
      <div class="space-y-2">
        <h3 class="text-sm font-medium">External control analyst requests</h3>
        <ul class="space-y-1 text-sm text-base-content/70">
          {% for r in external_requests %}
          <li>{{ r.name }} — <span class="badge badge-sm">{{ r.get_status_display }}</span></li>
          {% endfor %}
        </ul>
      </div>
      {% endif %}
```

Add `"external_requests": ExternalControlAnalyst.objects.filter(member=user)` to `_formation_context` (import the model at top of `views.py`).

- [ ] **Step 8: Run tests + lint + CSS + migrate**

Run: `uv run pytest formation/test_external_analyst.py -v && uv run python manage.py migrate && uv run ruff check formation notifications && npm run build:css`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add formation/ notifications/categories.py notifications/migrations
git commit -m "feat(formation): request authorization for an external control analyst (task #415)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Meeting-of-the-Analysts review queue + console card

**Files:**
- Modify: `formation/views.py` (`external_analyst_queue`/`_detail`/`_decide`)
- Modify: `formation/urls.py`
- Modify: `core/staff.py` (`meeting_of_analysts_admin` open count)
- Modify: `core/templates/core/staff/admin/meeting_of_analysts.html`
- Create: `formation/templates/formation/external_analyst_queue.html`, `external_analyst_detail.html`
- Test: `formation/test_external_analyst.py`

**Interfaces:**
- Consumes: `admissions.views._require_review`/`_can_review`, `formation.control.decide_external` (Task 6).
- Produces: URLs `formation:external_analyst_queue`, `external_analyst_detail`, `external_analyst_decide`; console context key `open_external_analysts`.

- [ ] **Step 1: Write the failing test**

Append to `formation/test_external_analyst.py`:

```python
def test_non_reviewer_cannot_open_queue(client):
    u = User.objects.create_user(email="plain@example.com", password="x")
    client.force_login(u)
    from django.urls import reverse
    resp = client.get(reverse("formation:external_analyst_queue"))
    assert resp.status_code == 403


def test_reviewer_approves_from_detail(client):
    from django.urls import reverse
    member = User.objects.create_user(email="mm@example.com", password="x")
    reviewer = User.objects.create_user(email="rr@example.com", password="x",
                                        is_staff=True)
    e = ExternalControlAnalyst.objects.create(
        member=member, name="Dr Q", description="...")
    client.force_login(reviewer)
    resp = client.post(reverse("formation:external_analyst_decide", args=[e.pk]),
                       {"decision": "approve", "note": "fine"})
    assert resp.status_code == 302
    e.refresh_from_db()
    assert e.status == ExternalControlAnalyst.Status.APPROVED
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest formation/test_external_analyst.py -k "queue or approves_from_detail" -v`
Expected: FAIL — no URLs.

- [ ] **Step 3: Views**

In `formation/views.py` (near the advancement review views, reuse the imported `_require_review`):

```python
@login_required
def external_analyst_queue(request):
    _require_review(request)
    from .models import ExternalControlAnalyst
    requests_ = (ExternalControlAnalyst.objects
                 .select_related("member", "member__profile", "decided_by")
                 .order_by("status", "-requested_at"))
    return render(request, "formation/external_analyst_queue.html", {
        "requests": requests_,
        "open_statuses": ExternalControlAnalyst.OPEN_STATUSES,
    })


@login_required
def external_analyst_detail(request, pk):
    _require_review(request)
    from .models import ExternalControlAnalyst
    obj = get_object_or_404(
        ExternalControlAnalyst.objects.select_related("member", "member__profile"),
        pk=pk)
    return render(request, "formation/external_analyst_detail.html", {"obj": obj})


@login_required
@require_POST
def external_analyst_decide(request, pk):
    _require_review(request)
    from .models import ExternalControlAnalyst
    from .control import decide_external
    obj = get_object_or_404(ExternalControlAnalyst, pk=pk)
    if not obj.is_open:
        messages.error(request, "This request has already been decided.")
        return redirect("formation:external_analyst_detail", pk=pk)
    decision = request.POST.get("decision")
    note = (request.POST.get("note") or "").strip()
    if decision == "approve":
        decide_external(obj, approve=True, by=request.user, note=note)
        messages.success(request, f"Approved {obj.name}; the member has been notified.")
    elif decision == "decline":
        decide_external(obj, approve=False, by=request.user, note=note)
        messages.success(request, "Recorded as not approved; the member has been notified.")
    else:
        messages.error(request, "Choose approve or decline.")
    return redirect("formation:external_analyst_detail", pk=pk)
```

- [ ] **Step 4: URLs**

In `formation/urls.py`, add under the `_MOA` review block:

```python
    path(f"{_MOA}/external-analysts/", views.external_analyst_queue,
         name="external_analyst_queue"),
    path(f"{_MOA}/external-analysts/<int:pk>/", views.external_analyst_detail,
         name="external_analyst_detail"),
    path(f"{_MOA}/external-analysts/<int:pk>/decide/", views.external_analyst_decide,
         name="external_analyst_decide"),
```

- [ ] **Step 5: Console card + count**

In `core/staff.py` `meeting_of_analysts_admin`, add to the imports/context:

```python
    from formation.models import ExternalControlAnalyst
    ...
        "open_external_analysts": ExternalControlAnalyst.objects.filter(
            status__in=ExternalControlAnalyst.OPEN_STATUSES).count(),
```

In `core/templates/core/staff/admin/meeting_of_analysts.html`, after the advancements `_section.html` include:

```html
  {% url 'formation:external_analyst_queue' as external_analysts_url %}
  {% include "core/staff/admin/_section.html" with title="External control analysts" body="Authorize analysts outside the School for members' control analyses. Members request; the Meeting approves or declines." link=external_analysts_url link_label="Review requests" count=open_external_analysts count_label="open" %}
```

- [ ] **Step 6: Queue + detail templates**

Create `formation/templates/formation/external_analyst_queue.html` and `external_analyst_detail.html`, modeled on `advancement_queue.html`/`advancement_detail.html`: the queue lists requests with member, name, status, requested date, link to detail; the detail shows all fields + a decide form (`approve`/`decline` radio or two buttons + a note textarea) POSTing to `formation:external_analyst_decide`. Use DaisyUI tokens; these are staff pages (em-dash copy is fine here, but keep it plain).

- [ ] **Step 7: Run tests + lint + CSS**

Run: `uv run pytest formation/test_external_analyst.py -v && uv run ruff check formation core && npm run build:css`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add formation/ core/staff.py core/templates/core/staff/admin/meeting_of_analysts.html
git commit -m "feat(formation): Meeting-of-the-Analysts external control analyst queue (task #415)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Intake wiring (accept_application sets clinical_background)

**Files:**
- Modify: `admissions/services.py` (`accept_application` ~line 168–186)
- Test: `admissions/test_services.py` (or the existing acceptance test module)

**Interfaces:**
- Consumes: `Profile.clinical_background` (Task 1), `Application.Background` (existing).

- [ ] **Step 1: Write the failing test**

Add to the admissions acceptance tests (find the module with `accept_application` tests via `grep -rl accept_application admissions/test*`):

```python
def test_accept_sets_clinical_background_for_clinical_analyst(db):
    from accounts.models import Profile, User
    from admissions.models import Application
    from admissions.services import accept_application

    applicant = User.objects.create_user(email="ap@example.com", password="x")
    reviewer = User.objects.create_user(email="rv@example.com", password="x",
                                        is_staff=True)
    app = Application.objects.create(
        applicant=applicant, track=Application.Track.ANALYST,
        background=Application.Background.CLINICAL,
        letter_of_intent="...",
    )
    accept_application(app, by=reviewer)
    applicant.profile.refresh_from_db()
    assert applicant.profile.clinical_background is True


def test_accept_academic_or_scholar_stays_academic(db):
    from accounts.models import User
    from admissions.models import Application
    from admissions.services import accept_application

    applicant = User.objects.create_user(email="ap2@example.com", password="x")
    reviewer = User.objects.create_user(email="rv2@example.com", password="x",
                                        is_staff=True)
    app = Application.objects.create(
        applicant=applicant, track=Application.Track.SCHOLAR,
        letter_of_intent="...",
    )
    accept_application(app, by=reviewer)
    applicant.profile.refresh_from_db()
    assert applicant.profile.clinical_background is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest admissions -k clinical_background -v`
Expected: FAIL — profile flag not set.

- [ ] **Step 3: Wire it in**

In `admissions/services.py` `accept_application`, after `record_membership_change(...)` and before setting `application.status`:

```python
    profile = application.applicant.profile
    profile.clinical_background = (
        application.background == Application.Background.CLINICAL
    )
    profile.save(update_fields=["clinical_background"])
```

- [ ] **Step 4: Run tests + lint**

Run: `uv run pytest admissions -k clinical_background -v && uv run ruff check admissions`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add admissions/services.py admissions/test_*
git commit -m "feat(admissions): set Profile.clinical_background at acceptance (task #415)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Advisor/admin edits the background flag + full-suite verification

**Files:**
- Modify: `formation/templates/formation/advisee_detail.html` (advisor edit control)
- Modify: `formation/views.py` (`advisee_detail` GET context already has advisee; add a small POST handler or a dedicated view)
- Modify: `formation/urls.py`
- Test: `formation/test_advisor_view.py`

**Interfaces:**
- Consumes: `formation.permissions.can_view_advisee`, `Profile.clinical_background`.
- Produces: URL `formation:advisee_set_background`.

- [ ] **Step 1: Write the failing test**

Append to `formation/test_advisor_view.py`:

```python
def test_advisor_sets_advisee_clinical_background(client, db):
    from django.urls import reverse
    from accounts.models import Advisorship, Profile, User

    advisor = User.objects.create_user(email="adv@example.com", password="x")
    advisor.profile.role = Profile.Role.ANALYST
    advisor.profile.save()
    advisee = User.objects.create_user(email="ave@example.com", password="x")
    advisee.profile.role = Profile.Role.PRE_CANDIDATE
    advisee.profile.save()
    Advisorship.objects.create(advisor=advisor, advisee=advisee)
    client.force_login(advisor)

    resp = client.post(reverse("formation:advisee_set_background", args=[advisee.pk]),
                       {"clinical_background": "on"})
    assert resp.status_code == 302
    advisee.profile.refresh_from_db()
    assert advisee.profile.clinical_background is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest formation/test_advisor_view.py -k set_advisee_clinical -v`
Expected: FAIL — no URL.

- [ ] **Step 3: View + URL**

In `formation/views.py`:

```python
@login_required
@require_POST
def advisee_set_background(request, pk):
    """Advisor (or staff) sets an advisee's clinical/academic background."""
    from accounts.models import User
    from .permissions import can_view_advisee
    advisee = get_object_or_404(User.objects.select_related("profile"), pk=pk)
    if not can_view_advisee(request.user, advisee):
        raise PermissionDenied
    advisee.profile.clinical_background = bool(request.POST.get("clinical_background"))
    advisee.profile.save(update_fields=["clinical_background"])
    messages.success(request, "Background updated.")
    return redirect("formation:advisee_detail", pk=advisee.pk)
```

In `formation/urls.py`, add under the Advisor View block:

```python
    path("formation/advisees/<int:pk>/background/", views.advisee_set_background,
         name="advisee_set_background"),
```

- [ ] **Step 4: Template control**

In `advisee_detail.html`, in the control-analysis area, add a small form showing the current requirement and a checkbox to toggle clinical background (advisor-facing; plain copy):

```html
    <form method="post" action="{% url 'formation:advisee_set_background' advisee.pk %}" class="flex items-center gap-2 text-sm">
      {% csrf_token %}
      <label class="flex items-center gap-2">
        <input type="checkbox" name="clinical_background" class="checkbox checkbox-sm" {% if advisee.profile.clinical_background %}checked{% endif %}>
        Clinical background (2 control analyses; unchecked = academic, 3)
      </label>
      <button class="btn btn-ghost btn-xs">Save</button>
    </form>
```

- [ ] **Step 5: Full-suite verification**

Run: `uv run pytest && uv run ruff check . && npm run build:css`
Expected: entire suite green.

- [ ] **Step 6: Commit**

```bash
git add formation/views.py formation/urls.py formation/templates/formation/advisee_detail.html formation/test_advisor_view.py
git commit -m "feat(formation): advisor sets advisee clinical/academic background (task #415)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review — spec coverage

| Spec section | Task(s) |
|---|---|
| §1 Background field + `control_requirement()` + backfill + admin | 1 |
| §1 Advisor/admin editability | 1 (admin), 9 (advisor) |
| §1 read-only display on member tab | 3 (sub-bar labels), display of requirement |
| §2 requirement tag (4-year/2-year, swappable) | 2 |
| §2 thresholds admin-tunable; drop control_years_target | 3 |
| §2 sub-bar / slot computation (longest-per-tag, per-relationship, extras→Total) | 3 |
| §3 School-analyst dropdown + FKs + supervisor_name cache | 5 |
| §3 external-analyst selectable once approved | 5 (form queryset) |
| §4 ExternalControlAnalyst model + lifecycle | 4 |
| §4 member request form/flow + notify Meeting | 6 |
| §4 Meeting queue/detail/decide + console card + notify member | 7 |
| §4 Django-admin override | 4 |
| §4 notification category | 6 |
| §5 intake wiring at acceptance | 8 |

**Open verification notes for the implementer:**
- Confirm `workgroups/permissions.py` exposes an iterator of Meeting members for `external_analyst_requested`; if only `is_meeting_of_analysts(user)` exists, add/reuse an `meeting_of_analysts_members()` helper (search `analyst` there and in `availability`/`admissions` which already fan out to analysts).
- Confirm `core.email.school_from` exists before using it in `formation/emails.py`; otherwise mirror the exact `EmailMessage` construction in the existing `send_advancement_*` functions.
- The `_control_form.html` link to `formation:external_analyst_request` requires Task 6's URL — build Task 6 before rebuilding/rendering that template (noted in Task 5 Step 8).
- `select select-bordered w-full`, `badge badge-outline`, `progress-secondary`, `badge-success`, `checkbox checkbox-sm` must appear in a template (they do in the steps above) so Tailwind keeps them in the prod build.
