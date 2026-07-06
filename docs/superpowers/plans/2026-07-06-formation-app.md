# Formation App + My Formation Enhancements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract a `formation` Django app out of `admissions` (moving the `Advancement`/palimpsest model and the member "My LSP" hub with zero data loss), then add member-reported control-analysis tracking, typed external activities, and an advisor read + private-notes view.

**Architecture:** New `formation` app holds the ongoing-formation domain; `admissions` keeps only intake (Application/interview/review). The `Advancement` table is moved via `SeparateDatabaseAndState` so no SQL runs against the existing table. New records are member-owned CRUD on the Formation tab; the Advisor View is a gated read-only surface with advisor-private notes.

**Tech Stack:** Django 5.2, Python 3.10, pytest-django, uv, Tailwind v4 + DaisyUI (semantic tokens only).

## Global Constraints

- Django 5.2 LTS, Python 3.10+; deps via `uv` (`uv run …`, `uv sync`).
- `accounts.User` is the custom user model — extend, never swap. Every User has a `Profile` (post-save signal).
- Tests: pytest-django (`uv run pytest`), lint `uv run ruff check .`. Keep both green — CI runs on push.
- Templates use DaisyUI **semantic tokens** (`bg-base-100`, `text-base-content`, `text-primary`) — never hardcoded colors. Tailwind scans templates only; classes set in Python must also appear in a template.
- **Member-facing site copy uses commas, not em dashes** (task #352 decision) — applies to any new copy here.
- Do-not-over-automate: member records are self-reported with no approval gate; no software enforcement of formation requirements beyond an informational meter.
- Frequent commits; each task ends green.
- New models live in `formation`. Preserve the existing `Advancement` DB table (`admissions_advancement`) and its palimpsest file paths.

---

## Phase 1 — Extraction (no behavior change)

The whole point of Phase 1 is that the site behaves identically afterward; only the code's home changes. The test suite is the oracle: it must be green at the end with the same assertions (updated only for the `admissions:` → `formation:` url-namespace rename).

### Task 1: Create the `formation` app and move `Advancement` (table-preserving)

**Files:**
- Create: `formation/__init__.py`, `formation/apps.py`, `formation/models.py`, `formation/migrations/__init__.py`, `formation/migrations/0001_initial.py`, `formation/admin.py`
- Modify: `config/settings/base.py:58` (INSTALLED_APPS), `admissions/models.py` (remove `Advancement`), `admissions/admin.py` (remove Advancement admin), create `admissions/migrations/00NN_drop_advancement_state.py`
- Test: `formation/tests_extraction.py`

**Interfaces:**
- Produces: `formation.models.Advancement` (same fields/behavior as today, `Meta.db_table = "admissions_advancement"`). All current `Advancement` attributes and methods are preserved verbatim.

- [ ] **Step 1: Scaffold the app**

Run:
```bash
uv run python manage.py startapp formation
```
Then set `formation/apps.py`:
```python
from django.apps import AppConfig


class FormationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "formation"
```

- [ ] **Step 2: Register the app**

In `config/settings/base.py`, add `"formation",` to `INSTALLED_APPS` immediately after `"admissions",`.

- [ ] **Step 3: Move the `Advancement` model definition**

Cut the entire `Advancement` class (and any module-level constant used only by it, e.g. `advancement`-only helpers) from `admissions/models.py` into `formation/models.py`. Preserve imports it needs. Add an explicit table name so the DB object is untouched:
```python
class Advancement(models.Model):
    # ... all existing fields/methods unchanged ...

    class Meta:
        db_table = "admissions_advancement"
        # copy any existing Meta options (ordering, etc.) from the old model
```
The palimpsest `FileField` uses `cv_storage` — import it from its current home (`from admissions.storage import cv_storage`) or move `cv_storage` into `formation/storage.py` if it is formation-only. Check `admissions/storage.py`: if `cv_storage` is shared with `Application.cv`, import it from `admissions`; do not duplicate it.

- [ ] **Step 4: Generate the paired state-only migrations**

Create `formation/migrations/0001_initial.py` as a normal `CreateModel` for `Advancement`, then wrap it so it only changes Django's state (no SQL — the table already exists):
```python
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("admissions", "<latest_admissions_migration>"),
        # plus accounts for the member FK
    ]
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="Advancement",
                    fields=[
                        # paste the full field list Django would generate,
                        # matching the current admissions_advancement columns exactly
                    ],
                    options={"db_table": "admissions_advancement"},
                ),
            ],
            database_operations=[],  # table already exists — no SQL
        ),
    ]
```
And in `admissions/migrations/00NN_drop_advancement_state.py`, remove it from `admissions` state only:
```python
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("admissions", "<prev>"), ("formation", "0001_initial")]
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="Advancement")],
            database_operations=[],
        ),
    ]
```
Tip to get the exact `state_operations` field list: temporarily run `uv run python manage.py makemigrations formation` with `Advancement` in `formation/models.py`, copy the generated `CreateModel.fields`, then hand-wrap it in `SeparateDatabaseAndState` and set `database_operations=[]`.

- [ ] **Step 5: Write the extraction regression test**

```python
# formation/tests_extraction.py
import pytest
from django.apps import apps


@pytest.mark.django_db
def test_advancement_lives_in_formation_on_the_same_table():
    Advancement = apps.get_model("formation", "Advancement")
    assert Advancement._meta.db_table == "admissions_advancement"


@pytest.mark.django_db
def test_migrations_have_no_pending_changes():
    # Fails if state and models drift (the SeparateDatabaseAndState split is wrong).
    from django.core.management import call_command
    call_command("makemigrations", "--check", "--dry-run", "formation", "admissions")
```

- [ ] **Step 6: Run migrations against a scratch DB and the tests**

Run:
```bash
uv run python manage.py migrate
uv run pytest formation/tests_extraction.py -q
```
Expected: migrate applies cleanly (no CREATE TABLE for advancement); tests PASS. If `makemigrations --check` reports drift, reconcile the `state_operations` field list with the model.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "formation: extract Advancement to new app (table-preserving)"
```

### Task 2: Move the member hub + advancement/advise views, templates, urls

**Files:**
- Create: `formation/views.py`, `formation/urls.py`, `formation/advancement.py`, `formation/tabs.py`, `formation/context_processors.py`, `formation/forms.py`, `formation/notifications.py`, `formation/emails.py`, `formation/templates/formation/…`
- Modify: `config/urls.py` (point `/formation/`, `/admin-tools/meeting-of-analysts/advancements/…` at `formation.urls`; keep `admissions.urls` for the rest), `config/settings/base.py:116` (context_processor path), and every template/py referencing the moved `admissions:` url-names
- Delete from `admissions`: the moved views/urls/templates

**Interfaces:**
- Produces: url namespace `formation:` with names `formation`, `advancement`, `advancement_withdraw`, `palimpsest_download`, `advise_queue`, `advise_present`, `advancement_queue`, `advancement_detail`, `advancement_decide` (paths unchanged).

- [ ] **Step 1: Move the code files**

```bash
git mv admissions/advancement.py formation/advancement.py
```
Move the formation-only view functions from `admissions/views.py` into `formation/views.py`: `formation`, `_formation_url`, `_formation_context`, `_has_money_history`, `_formation_track_for`, `_formation_steps`, `_formation_money_context`, `_tuition_progress`, `_formation_groups_events_context`, `advancement`, `advancement_withdraw`, `palimpsest_download`, `advise_queue`, `advise_present`, `advancement_queue`, `advancement_detail`, `advancement_decide`. Leave the intake views (`apply*`, `status`, `cv_download`, `review_*`) in `admissions/views.py`. Move `admissions/tabs.py` and `admissions/context_processors.py` (the `my_lsp_tabs` processor) to `formation/`. Move `admissions/forms.py` advancement/advisor forms into `formation/forms.py` (split the file; leave application forms in `admissions/forms.py`).

- [ ] **Step 2: Move templates**

```bash
mkdir -p formation/templates/formation
git mv admissions/templates/admissions/formation.html formation/templates/formation/formation.html
git mv admissions/templates/admissions/advancement_detail.html formation/templates/formation/
git mv admissions/templates/admissions/advancement_queue.html formation/templates/formation/
git mv admissions/templates/admissions/advise_queue.html formation/templates/formation/
git mv admissions/templates/admissions/_tab_formation.html formation/templates/formation/
git mv admissions/templates/admissions/_tab_tuition.html formation/templates/formation/
git mv admissions/templates/admissions/_tab_dues.html formation/templates/formation/
git mv admissions/templates/admissions/_tab_groups.html formation/templates/formation/
git mv admissions/templates/admissions/_tab_events.html formation/templates/formation/
git mv admissions/templates/admissions/_tab_works.html formation/templates/formation/
git mv admissions/templates/admissions/_tab_proposals.html formation/templates/formation/
git mv admissions/templates/admissions/_tab_profile.html formation/templates/formation/
git mv admissions/templates/admissions/_tab_suggestions.html formation/templates/formation/
git mv admissions/templates/admissions/_my_payments_table.html formation/templates/formation/
```
Update `render(...)` template paths and `{% include %}`/`{% extends %}` references from `admissions/…` to `formation/…` inside the moved views and templates.

- [ ] **Step 3: Create `formation/urls.py`**

Move the formation url patterns out of `admissions/urls.py` into a new `formation/urls.py` with `app_name = "formation"`, keeping the exact paths:
```python
from django.urls import path
from . import views

app_name = "formation"
_MOA = "admin-tools/meeting-of-analysts"

urlpatterns = [
    path("formation/", views.formation, name="formation"),
    path("formation/demande/", views.advancement, name="advancement"),
    path("formation/<int:pk>/withdraw/", views.advancement_withdraw, name="advancement_withdraw"),
    path("formation/<int:pk>/palimpsest/", views.palimpsest_download, name="palimpsest_download"),
    path("formation/advise/", views.advise_queue, name="advise_queue"),
    path("formation/advise/<int:pk>/present/", views.advise_present, name="advise_present"),
    path(f"{_MOA}/advancements/", views.advancement_queue, name="advancement_queue"),
    path(f"{_MOA}/advancements/<int:pk>/", views.advancement_detail, name="advancement_detail"),
    path(f"{_MOA}/advancements/<int:pk>/decide/", views.advancement_decide, name="advancement_decide"),
]
```
Remove those patterns from `admissions/urls.py`. In `config/urls.py`, include `formation.urls` (no extra prefix — paths are absolute) alongside the existing `admissions.urls` include.

- [ ] **Step 4: Update the settings context-processor path**

In `config/settings/base.py`, change `"admissions.context_processors.my_lsp_tabs"` to `"formation.context_processors.my_lsp_tabs"`.

- [ ] **Step 5: Re-namespace all references**

Find every `admissions:` reference to a moved name and change it to `formation:`:
```bash
grep -rn "admissions:\(formation\|advancement\|advancement_withdraw\|palimpsest_download\|advise_queue\|advise_present\|advancement_queue\|advancement_detail\|advancement_decide\)" --include=*.py --include=*.html .
```
Update each hit (templates, `reverse()`/`redirect()` calls, tests). Leave `admissions:apply*`, `admissions:status`, `admissions:cv_download`, `admissions:review_*` untouched. Also update Python imports: anything importing `from admissions.models import Advancement` becomes `from formation.models import Advancement`; `from admissions.advancement import …` becomes `from formation.advancement import …`.

- [ ] **Step 6: Run the check + full suite**

Run:
```bash
uv run python manage.py check
uv run pytest -q
```
Expected: check clean; suite green except the moved tests (next task). Fix any `NoReverseMatch`/import errors surfaced here.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "formation: move hub + advancement views/templates/urls, re-namespace"
```

### Task 3: Move the formation tests

**Files:**
- Move: `admissions/test_advancement.py` → `formation/test_advancement.py`; `admissions/test_formation.py` → `formation/test_formation.py`; `admissions/test_my_lsp.py` → `formation/test_my_lsp.py`
- Modify: the moved tests' imports + url names

- [ ] **Step 1: Move the test files**

```bash
git mv admissions/test_advancement.py formation/test_advancement.py
git mv admissions/test_formation.py formation/test_formation.py
git mv admissions/test_my_lsp.py formation/test_my_lsp.py
```

- [ ] **Step 2: Fix imports and url-names in the moved tests**

Update `from admissions.models import Advancement` → `from formation.models import Advancement`, and `reverse("admissions:formation")` etc. → `reverse("formation:…")` for the moved names.

- [ ] **Step 3: Run the full suite**

Run:
```bash
uv run pytest -q
```
Expected: PASS (same behavior, new home). Also run `uv run ruff check .`.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "formation: move advancement/formation/my-lsp tests"
```

---

## Phase 2 — Control-analysis tracking (#361)

### Task 4: `FormationSettings` singleton + `ControlAnalysis` model

**Files:**
- Modify: `formation/models.py`, `formation/admin.py`
- Create: `formation/migrations/0002_control_analysis.py` (via makemigrations)
- Test: `formation/test_control.py`

**Interfaces:**
- Produces:
  - `FormationSettings.load()` → the singleton row; `.control_years_target` (int, default 6).
  - `ControlAnalysis(member, supervisor_name, modality, start_date, end_date=None, notes="")`; `ControlAnalysis.years_for(user) -> float` classmethod returning total control years; instance `.duration_years -> float`.

- [ ] **Step 1: Write failing tests**

```python
# formation/test_control.py
import datetime as dt
import pytest
from accounts.models import User
from formation.models import ControlAnalysis, FormationSettings


@pytest.mark.django_db
def test_closed_entry_duration_in_years():
    u = User.objects.create_user(email="m@x.test")
    ca = ControlAnalysis.objects.create(
        member=u, supervisor_name="Dr Ferenczi", modality="remote",
        start_date=dt.date(2020, 1, 1), end_date=dt.date(2023, 1, 1),
    )
    assert round(ca.duration_years, 1) == 3.0


@pytest.mark.django_db
def test_ongoing_entry_counts_to_today(settings):
    u = User.objects.create_user(email="m2@x.test")
    ca = ControlAnalysis.objects.create(
        member=u, supervisor_name="Dr Klein", modality="in_person",
        start_date=dt.date.today() - dt.timedelta(days=365),
    )
    assert 0.9 < ca.duration_years < 1.1


@pytest.mark.django_db
def test_total_years_sums_entries():
    u = User.objects.create_user(email="m3@x.test")
    for s, e in [((2018, 1, 1), (2019, 1, 1)), ((2019, 1, 1), (2021, 1, 1))]:
        ControlAnalysis.objects.create(
            member=u, supervisor_name="S", modality="remote",
            start_date=dt.date(*s), end_date=dt.date(*e),
        )
    assert round(ControlAnalysis.years_for(u), 1) == 3.0


@pytest.mark.django_db
def test_settings_default_target_is_six():
    assert FormationSettings.load().control_years_target == 6
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest formation/test_control.py -q`
Expected: FAIL (models don't exist).

- [ ] **Step 3: Implement the models**

```python
# formation/models.py (append)
import datetime as dt
from django.conf import settings
from django.db import models


class FormationSettings(models.Model):
    """Singleton of tunable formation parameters (admin-editable so requirement
    targets don't live in code)."""
    control_years_target = models.PositiveSmallIntegerField(
        default=6,
        help_text="Target years of control analysis shown on the progress meter.",
    )

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ControlAnalysis(models.Model):
    """A member's self-reported control (supervisory) analysis. No approval:
    a personal formation record, readable by the member's advisor + staff."""

    class Modality(models.TextChoices):
        IN_PERSON = "in_person", "In person"
        REMOTE = "remote", "Remote"
        HYBRID = "hybrid", "Hybrid"

    member = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="control_analyses")
    supervisor_name = models.CharField(max_length=200)
    modality = models.CharField(max_length=12, choices=Modality.choices, default=Modality.REMOTE)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True, help_text="Leave blank if ongoing.")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-start_date",)

    @property
    def duration_years(self) -> float:
        end = self.end_date or dt.date.today()
        return max(0.0, (end - self.start_date).days / 365.25)

    @classmethod
    def years_for(cls, user) -> float:
        return round(sum(c.duration_years for c in cls.objects.filter(member=user)), 2)
```

- [ ] **Step 4: Make + run migration, run tests**

Run:
```bash
uv run python manage.py makemigrations formation
uv run pytest formation/test_control.py -q
```
Expected: PASS.

- [ ] **Step 5: Register in admin**

```python
# formation/admin.py
from django.contrib import admin
from .models import ControlAnalysis, FormationSettings

admin.site.register(FormationSettings)


@admin.register(ControlAnalysis)
class ControlAnalysisAdmin(admin.ModelAdmin):
    list_display = ("member", "supervisor_name", "modality", "start_date", "end_date")
    search_fields = ("member__email", "supervisor_name")
```

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "formation: ControlAnalysis + FormationSettings models"
```

### Task 5: Control-analysis member CRUD + progress meter on the Formation tab

**Files:**
- Modify: `formation/views.py`, `formation/urls.py`, `formation/forms.py`, `formation/templates/formation/_tab_formation.html`
- Create: `formation/templates/formation/_control_form.html`
- Test: `formation/test_control_views.py`

**Interfaces:**
- Consumes: `ControlAnalysis`, `FormationSettings.load()`, `ControlAnalysis.years_for`.
- Produces: url names `control_add`, `control_edit`, `control_delete`; context keys `control_entries`, `control_years`, `control_target` on the Formation tab.

- [ ] **Step 1: Write failing view tests**

```python
# formation/test_control_views.py
import datetime as dt
import pytest
from django.urls import reverse
from accounts.models import User
from formation.models import ControlAnalysis


@pytest.mark.django_db
def test_member_adds_control_entry(client):
    u = User.objects.create_user(email="c@x.test", password="x")
    client.force_login(u)
    resp = client.post(reverse("formation:control_add"), {
        "supervisor_name": "Dr A", "modality": "remote",
        "start_date": "2021-01-01", "end_date": "", "notes": "",
    }, SERVER_NAME="localhost")
    assert resp.status_code in (302, 303)
    assert ControlAnalysis.objects.filter(member=u, supervisor_name="Dr A").exists()


@pytest.mark.django_db
def test_member_cannot_edit_others_entry(client):
    owner = User.objects.create_user(email="o@x.test")
    other = User.objects.create_user(email="x@x.test", password="x")
    ca = ControlAnalysis.objects.create(member=owner, supervisor_name="S",
        modality="remote", start_date=dt.date(2021, 1, 1))
    client.force_login(other)
    resp = client.post(reverse("formation:control_edit", args=[ca.pk]),
        {"supervisor_name": "H", "modality": "remote", "start_date": "2021-01-01"},
        SERVER_NAME="localhost")
    assert resp.status_code in (403, 404)
    ca.refresh_from_db()
    assert ca.supervisor_name == "S"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest formation/test_control_views.py -q`
Expected: FAIL (no such url).

- [ ] **Step 3: Add the form**

```python
# formation/forms.py (append)
from django import forms
from .models import ControlAnalysis


class ControlAnalysisForm(forms.ModelForm):
    class Meta:
        model = ControlAnalysis
        fields = ("supervisor_name", "modality", "start_date", "end_date", "notes")
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date", "class": "input input-bordered w-full"}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "input input-bordered w-full"}),
            "supervisor_name": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "modality": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "textarea textarea-bordered w-full"}),
        }
```

- [ ] **Step 4: Add the views**

```python
# formation/views.py (append)
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from .forms import ControlAnalysisForm
from .models import ControlAnalysis, FormationSettings


@login_required
def control_add(request):
    if request.method == "POST":
        form = ControlAnalysisForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.member = request.user
            obj.save()
            return redirect(_formation_url("formation"))
    else:
        form = ControlAnalysisForm()
    return render(request, "formation/_control_form.html", {"form": form, "mode": "add"})


@login_required
def control_edit(request, pk):
    obj = get_object_or_404(ControlAnalysis, pk=pk, member=request.user)
    if request.method == "POST":
        form = ControlAnalysisForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            return redirect(_formation_url("formation"))
    else:
        form = ControlAnalysisForm(instance=obj)
    return render(request, "formation/_control_form.html", {"form": form, "mode": "edit"})


@login_required
def control_delete(request, pk):
    obj = get_object_or_404(ControlAnalysis, pk=pk, member=request.user)
    if request.method == "POST":
        obj.delete()
    return redirect(_formation_url("formation"))
```
Note: `member=request.user` in `get_object_or_404` yields 404 for a non-owner — this is the ownership gate the test asserts.

- [ ] **Step 5: Wire urls**

```python
# formation/urls.py (add to urlpatterns)
    path("formation/control/add/", views.control_add, name="control_add"),
    path("formation/control/<int:pk>/edit/", views.control_edit, name="control_edit"),
    path("formation/control/<int:pk>/delete/", views.control_delete, name="control_delete"),
```

- [ ] **Step 6: Add context + render the section + meter**

In `_formation_context` (the Formation-tab builder), add:
```python
    ctx["control_entries"] = ControlAnalysis.objects.filter(member=user)
    ctx["control_years"] = ControlAnalysis.years_for(user)
    ctx["control_target"] = FormationSettings.load().control_years_target
```
In `formation/templates/formation/_tab_formation.html`, add a "Control analyses" section: a list of entries (supervisor, date range, modality) with edit/delete, an "Add" link to `formation:control_add`, and a progress meter using DaisyUI:
```html
<progress class="progress progress-primary w-full" value="{{ control_years }}" max="{{ control_target }}"></progress>
<p class="text-sm text-base-content/70">{{ control_years }} of {{ control_target }} years of control analysis, or four years of ongoing dialogue with an analyst.</p>
```
Create `formation/templates/formation/_control_form.html` extending `core/base.html` with the form (DaisyUI inputs already set via widget attrs).

- [ ] **Step 7: Run tests + a live render**

Run:
```bash
uv run pytest formation/test_control_views.py -q
uv run python manage.py migrate --run-syncdb -v0
uv run python manage.py shell -c "from django.test import Client; from accounts.models import User; u=User.objects.create_user(email='z@x.test',password='x'); c=Client(); c.force_login(u); print(c.get('/formation/', SERVER_NAME='localhost').status_code)"
```
Expected: tests PASS; hub returns 200.

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "formation: control-analysis CRUD + progress meter on Formation tab"
```

---

## Phase 3 — External activities (#363)

### Task 6: `ExternalActivity` model + member CRUD + typed list

**Files:**
- Modify: `formation/models.py`, `formation/admin.py`, `formation/forms.py`, `formation/views.py`, `formation/urls.py`, `formation/templates/formation/_tab_formation.html`
- Create: `formation/migrations/0003_external_activity.py`, `formation/templates/formation/_external_form.html`
- Test: `formation/test_external.py`

**Interfaces:**
- Produces: `ExternalActivity(member, kind, title, venue="", start_date, end_date=None, url="", notes="")`; url names `external_add`, `external_edit`, `external_delete`; context key `external_entries`.

- [ ] **Step 1: Write failing tests**

```python
# formation/test_external.py
import pytest
from django.urls import reverse
from accounts.models import User
from formation.models import ExternalActivity


@pytest.mark.django_db
def test_member_adds_external_activity(client):
    u = User.objects.create_user(email="e@x.test", password="x")
    client.force_login(u)
    resp = client.post(reverse("formation:external_add"), {
        "kind": "course_taught", "title": "Reading Seminar XI",
        "venue": "CIIS", "start_date": "2025-09-01", "end_date": "",
        "url": "", "notes": "",
    }, SERVER_NAME="localhost")
    assert resp.status_code in (302, 303)
    assert ExternalActivity.objects.filter(member=u, title="Reading Seminar XI").exists()


@pytest.mark.django_db
def test_member_cannot_delete_others_activity(client):
    owner = User.objects.create_user(email="o2@x.test")
    other = User.objects.create_user(email="x2@x.test", password="x")
    a = ExternalActivity.objects.create(member=owner, kind="publication",
        title="T", start_date="2024-01-01")
    client.force_login(other)
    resp = client.post(reverse("formation:external_delete", args=[a.pk]), SERVER_NAME="localhost")
    assert resp.status_code in (403, 404)
    assert ExternalActivity.objects.filter(pk=a.pk).exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest formation/test_external.py -q` — Expected: FAIL.

- [ ] **Step 3: Implement the model**

```python
# formation/models.py (append)
class ExternalActivity(models.Model):
    """A member's self-reported related activity outside LSP (e.g. taking or
    teaching a course on Lacan). Self-reported, no approval."""

    class Kind(models.TextChoices):
        COURSE_TAKEN = "course_taken", "Course taken"
        COURSE_TAUGHT = "course_taught", "Course taught"
        PRESENTATION = "presentation", "Presentation"
        PUBLICATION = "publication", "Publication"
        OTHER = "other", "Other"

    member = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="external_activities")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    title = models.CharField(max_length=300)
    venue = models.CharField(max_length=200, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    url = models.URLField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-start_date",)
```

- [ ] **Step 4: Make migration + run model tests**

Run: `uv run python manage.py makemigrations formation && uv run pytest formation/test_external.py -q`
(Views still missing — the two view tests fail until Step 5-6; the model import now works.)

- [ ] **Step 5: Form + views + urls**

Add `ExternalActivityForm` (ModelForm over `kind, title, venue, start_date, end_date, url, notes` with DaisyUI widget classes), and `external_add` / `external_edit` / `external_delete` views mirroring the control views exactly (owner gate via `get_object_or_404(ExternalActivity, pk=pk, member=request.user)`, redirect to `_formation_url("formation")`). Register urls:
```python
    path("formation/external/add/", views.external_add, name="external_add"),
    path("formation/external/<int:pk>/edit/", views.external_edit, name="external_edit"),
    path("formation/external/<int:pk>/delete/", views.external_delete, name="external_delete"),
```

- [ ] **Step 6: Context + template section**

In `_formation_context` add `ctx["external_entries"] = ExternalActivity.objects.filter(member=user)`. In `_tab_formation.html` add an "External activities" section: list grouped/labelled by `get_kind_display`, each with title, venue, date, optional link, and edit/delete; an "Add" link to `formation:external_add`. Create `_external_form.html`.

- [ ] **Step 7: Run tests + live render**

Run: `uv run pytest formation/test_external.py -q` then GET `/formation/` (as in Task 5 Step 7). Expected: PASS + 200.

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "formation: external-activity CRUD + typed list on Formation tab"
```

---

## Phase 4 — Advisor View (#364)

### Task 7: `AdvisorNote` model + gated advisees list + read-only detail

**Files:**
- Modify: `formation/models.py`, `formation/admin.py`, `formation/views.py`, `formation/urls.py`, `formation/templates/formation/formation.html` (advisor entry point)
- Create: `formation/migrations/0004_advisor_note.py`, `formation/templates/formation/advisees.html`, `formation/templates/formation/advisee_detail.html`
- Test: `formation/test_advisor_view.py`

**Interfaces:**
- Consumes: `accounts.advisor.current_advisor`, `ControlAnalysis`, `ExternalActivity`, `Advancement`.
- Produces: `AdvisorNote(advisee, author, body)`; url names `advisees`, `advisee_detail`, `advisee_note_add`; helper `formation.permissions.can_view_advisee(viewer, advisee) -> bool`.

- [ ] **Step 1: Write failing tests**

```python
# formation/test_advisor_view.py
import pytest
from django.urls import reverse
from accounts.models import User
from formation.models import AdvisorNote


def _advisee_of(advisor):
    """Create a member whose current advisor is `advisor`."""
    from accounts.advisor import set_advisor  # use the real advisor-assignment API
    m = User.objects.create_user(email="advisee@x.test")
    set_advisor(m, advisor)  # if the API differs, adapt to the actual helper
    return m


@pytest.mark.django_db
def test_advisor_sees_advisee_detail(client):
    advisor = User.objects.create_user(email="adv@x.test", password="x")
    advisee = _advisee_of(advisor)
    client.force_login(advisor)
    resp = client.get(reverse("formation:advisee_detail", args=[advisee.pk]), SERVER_NAME="localhost")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_non_advisor_member_gets_403(client):
    advisor = User.objects.create_user(email="adv2@x.test")
    advisee = _advisee_of(advisor)
    stranger = User.objects.create_user(email="s@x.test", password="x")
    client.force_login(stranger)
    resp = client.get(reverse("formation:advisee_detail", args=[advisee.pk]), SERVER_NAME="localhost")
    assert resp.status_code in (403, 404)


@pytest.mark.django_db
def test_advisee_cannot_see_notes_about_self(client):
    advisor = User.objects.create_user(email="adv3@x.test")
    advisee = _advisee_of(advisor)
    AdvisorNote.objects.create(advisee=advisee, author=advisor, body="SECRET-NOTE")
    client.force_login(advisee)
    # The advisee's own Formation hub must never contain advisor notes.
    body = client.get("/formation/", SERVER_NAME="localhost").content.decode()
    assert "SECRET-NOTE" not in body
```
Before writing code, confirm the real advisor-assignment helper name in `accounts/advisor.py` (e.g. `set_advisor`, or creating an `Advisorship` row) and use it in `_advisee_of`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest formation/test_advisor_view.py -q` — Expected: FAIL.

- [ ] **Step 3: Model**

```python
# formation/models.py (append)
class AdvisorNote(models.Model):
    """A private note an advisor keeps on an advisee. Visible to the advisee's
    advisor(s) and staff — never to the advisee."""
    advisee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="advisor_notes_about")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="advisor_notes_written")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
```

- [ ] **Step 4: Permission helper**

```python
# formation/permissions.py (new)
from accounts.advisor import current_advisor
from core.staff import can_access_admin_tools  # or the appropriate staff check


def can_view_advisee(viewer, advisee) -> bool:
    if not getattr(viewer, "is_authenticated", False):
        return False
    if viewer.is_staff or can_access_admin_tools(viewer):
        return True
    return current_advisor(advisee) == viewer
```
Confirm the correct staff predicate import during implementation (`core.staff`); if unsure, use `viewer.is_staff` only plus the advisor check.

- [ ] **Step 5: Views + urls**

```python
# formation/views.py (append)
from django.core.exceptions import PermissionDenied
from .models import AdvisorNote
from .permissions import can_view_advisee
from accounts.advisor import current_advisor


@login_required
def advisees(request):
    from accounts.advisor import advisees_of  # confirm real helper; else query memberships
    rows = advisees_of(request.user)
    return render(request, "formation/advisees.html", {"advisees": rows})


@login_required
def advisee_detail(request, pk):
    advisee = get_object_or_404(User, pk=pk)
    if not can_view_advisee(request.user, advisee):
        raise PermissionDenied
    ctx = {
        "advisee": advisee,
        "control_entries": ControlAnalysis.objects.filter(member=advisee),
        "control_years": ControlAnalysis.years_for(advisee),
        "control_target": FormationSettings.load().control_years_target,
        "external_entries": ExternalActivity.objects.filter(member=advisee),
        "advancements": Advancement.objects.filter(member=advisee),
        "notes": AdvisorNote.objects.filter(advisee=advisee),
    }
    return render(request, "formation/advisee_detail.html", ctx)


@login_required
def advisee_note_add(request, pk):
    advisee = get_object_or_404(User, pk=pk)
    if not can_view_advisee(request.user, advisee):
        raise PermissionDenied
    body = (request.POST.get("body") or "").strip()
    if body:
        AdvisorNote.objects.create(advisee=advisee, author=request.user, body=body)
    return redirect(reverse("formation:advisee_detail", args=[advisee.pk]))
```
`User` and `reverse` must be imported at the top of `formation/views.py`. Urls:
```python
    path("formation/advisees/", views.advisees, name="advisees"),
    path("formation/advisees/<int:pk>/", views.advisee_detail, name="advisee_detail"),
    path("formation/advisees/<int:pk>/note/", views.advisee_note_add, name="advisee_note_add"),
```

- [ ] **Step 6: Templates + entry point**

Create `advisees.html` (list linking each advisee to `advisee_detail`) and `advisee_detail.html` (read-only record + a notes panel: list `notes` and a POST form to `advisee_note_add`). In `formation.html`, where the advisor's `advise_queue` link already appears, add an "Advisees" link to `formation:advisees` (shown when `advisees_of(user)` is non-empty, or simply for any user — the list just renders empty otherwise). **Do not** render `AdvisorNote`s anywhere in `_tab_formation.html` or the member hub — notes appear only on `advisee_detail`.

- [ ] **Step 7: Make migration, run tests + full suite**

Run:
```bash
uv run python manage.py makemigrations formation
uv run pytest formation/ -q
uv run pytest -q
uv run ruff check .
```
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "formation: advisor view — advisees list, read-only detail, private notes"
```

---

## Self-review notes (coverage map)

- Extraction + hub move → Phase 1 (Tasks 1-3). Table-preserving move → Task 1 Step 4. Re-namespace → Task 2 Step 5.
- Control tracking (#361): model + settings → Task 4; CRUD + meter → Task 5.
- External activities (#363): Task 6.
- Advisor View + private notes (#364): Task 7.
- Visibility invariants: member-owner gate (Tasks 5/6 tests), advisor→advisee allow + stranger 403 + note hidden-from-advisee (Task 7 tests).
- Copy uses commas not em dashes (global constraint) — applies to the new template strings in Tasks 5-7.

## Known unknowns to confirm during implementation (not placeholders — verify against code)
- The exact advisor-assignment / advisee-lookup helpers in `accounts/advisor.py` (`current_advisor` is confirmed; confirm the setter and an `advisees_of`-style reverse lookup, or query the underlying model directly).
- Whether `cv_storage` is shared with `Application.cv` (import vs move).
- The precise generated field list for the `Advancement` `SeparateDatabaseAndState` `CreateModel` (copy from a throwaway `makemigrations`).
