# MoA-owned Formation Background Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a student's formation background a 3-state, MoA-owned, audited fact that correctly drives the control-analysis requirement — fixing the silent "academic by default" conflation.

**Architecture:** Widen `Profile.clinical_background` (bool) into a 3-state `formation_background` CharField (`unreviewed`/`clinical`/`academic`). All writes go through one `formation.background.set_background()` service that updates the profile, appends an immutable `BackgroundDetermination` audit row (actor/time/optional note), and rings the student's bell. Two entry points call it: an upgraded advisor form and a new Meeting-of-Analysts console surface (list + per-student history). The student's tracker shows a neutral "not yet set" state while unreviewed.

**Tech Stack:** Django 5.2, pytest-django, DaisyUI/Tailwind templates. Run tests with `uv run pytest`.

## Global Constraints

- Django 5.2 / Python 3.10+; deps via `uv` (`uv run pytest`, `uv run ruff check .`).
- Templates use DaisyUI semantic tokens only (`bg-base-100`, `text-base-content`, `text-primary`, …) — never hardcoded colors.
- Member-facing site copy uses commas, not em dashes (`em-dash-prose-style` memory).
- Keep tests + ruff green — CI runs them on push and a single failure aborts deploy.
- MoA review gate is `admissions.views._require_review(request)` (raises `PermissionDenied` for non-Analysts/non-staff); the "can view" predicate is `admissions.views._can_review(user)`.
- Notifications go through `notifications.dispatch.notify(...)`; formation wrappers live in `formation/notifications.py`.
- This is a worktree at `.claude-worktrees/olive-pike` — edit files here, not in the main checkout (`worktree-vs-main-path-trap` memory).

---

### Task 1: Widen the field — `Profile.formation_background` + requirement + migration

**Files:**
- Modify: `accounts/models.py` (field `clinical_background` → `formation_background`; `control_requirement()`)
- Create: `accounts/migrations/0035_formation_background.py` (AddField + data copy + RemoveField)
- Modify: `accounts/admin.py:112-113` (`list_display`, `list_filter`)
- Modify: `accounts/test_clinical_background.py` (rewrite for the new field; drop the superseded 0034 backfill test)
- Modify: `formation/test_control.py:56,90,104` (`clinical_background` → `formation_background`)

**Interfaces:**
- Produces: `Profile.FormationBackground` (TextChoices: `UNREVIEWED="unreviewed"`, `CLINICAL="clinical"`, `ACADEMIC="academic"`); `Profile.formation_background` (CharField, default `UNREVIEWED`); `Profile.control_requirement() -> dict | None` (None when unreviewed; `{"four_year":1,"two_year":1}` clinical; `{"four_year":1,"two_year":2}` academic).

- [ ] **Step 1: Write the failing test** — rewrite `accounts/test_clinical_background.py` entirely:

```python
import pytest

from accounts.models import Profile, User

pytestmark = pytest.mark.django_db


def _user(email, role):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


def test_default_background_is_unreviewed():
    u = _user("new@example.com", Profile.Role.PRE_CANDIDATE)
    assert u.profile.formation_background == Profile.FormationBackground.UNREVIEWED
    assert u.profile.control_requirement() is None


def test_clinical_requirement_two_analyses():
    u = _user("clin@example.com", Profile.Role.ANALYST)
    u.profile.formation_background = Profile.FormationBackground.CLINICAL
    assert u.profile.control_requirement() == {"four_year": 1, "two_year": 1}


def test_academic_requirement_three_analyses():
    u = _user("acad@example.com", Profile.Role.PRE_CANDIDATE)
    u.profile.formation_background = Profile.FormationBackground.ACADEMIC
    assert u.profile.control_requirement() == {"four_year": 1, "two_year": 2}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest accounts/test_clinical_background.py -q`
Expected: FAIL — `AttributeError: type object 'Profile' has no attribute 'FormationBackground'`.

- [ ] **Step 3: Implement the field + requirement.** In `accounts/models.py`, replace the `clinical_background` field (currently near line 155) with:

```python
class FormationBackground(models.TextChoices):
    UNREVIEWED = "unreviewed", "Not yet reviewed"
    CLINICAL = "clinical", "Clinical (one 4-year, one 2-year control analysis)"
    ACADEMIC = "academic", "Academic (one 4-year, two 2-year control analyses)"

formation_background = models.CharField(
    max_length=12,
    choices=FormationBackground.choices,
    default=FormationBackground.UNREVIEWED,
    help_text="The student's professional background, which sets the "
              "control-analysis requirement. Determined by the Meeting of "
              "Analysts or the student's advisor. Independent of the "
              "formation track.",
)
```

Replace `control_requirement()` (near line 561) with:

```python
def control_requirement(self) -> dict | None:
    """How many control analyses this member owes, by slot, or None when the
    Meeting of Analysts has not yet determined the background. Clinical: one
    4-year + one 2-year. Academic: one 4-year + two 2-year."""
    if self.formation_background == self.FormationBackground.CLINICAL:
        return {"four_year": 1, "two_year": 1}
    if self.formation_background == self.FormationBackground.ACADEMIC:
        return {"four_year": 1, "two_year": 2}
    return None
```

- [ ] **Step 4: Create the migration** `accounts/migrations/0035_formation_background.py`:

```python
from django.db import migrations, models


def copy_forward(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    Profile.objects.filter(clinical_background=True).update(formation_background="clinical")
    Profile.objects.filter(clinical_background=False).update(formation_background="unreviewed")


def copy_back(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    Profile.objects.filter(formation_background="clinical").update(clinical_background=True)
    Profile.objects.exclude(formation_background="clinical").update(clinical_background=False)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0034_profile_clinical_background")]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="formation_background",
            field=models.CharField(
                default="unreviewed", max_length=12,
                choices=[("unreviewed", "Not yet reviewed"),
                         ("clinical", "Clinical (one 4-year, one 2-year control analysis)"),
                         ("academic", "Academic (one 4-year, two 2-year control analyses)")],
            ),
        ),
        migrations.RunPython(copy_forward, copy_back),
        migrations.RemoveField(model_name="profile", name="clinical_background"),
    ]
```

Update `accounts/admin.py:112-113`: replace both `"clinical_background"` occurrences with `"formation_background"`.

Update `formation/test_control.py`: lines 56/90/104 — replace `u.profile.clinical_background = False` with `u.profile.formation_background = Profile.FormationBackground.ACADEMIC`, and `= True` (both occurrences) with `= Profile.FormationBackground.CLINICAL`. (Line 56's test expects `total_target == 8` → academic; lines 90/104 use clinical.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest accounts/test_clinical_background.py formation/test_control.py -q && uv run python manage.py makemigrations --check --dry-run`
Expected: PASS; `No changes detected` (schema matches migration).

- [ ] **Step 6: Commit**

```bash
git add accounts/models.py accounts/admin.py accounts/migrations/0035_formation_background.py accounts/test_clinical_background.py formation/test_control.py
git commit -m "feat(formation): 3-state formation_background replaces clinical_background bool (task #466)"
```

---

### Task 2: `control_progress` neutral (unreviewed) payload

**Files:**
- Modify: `formation/control.py` (`control_progress`)
- Modify: `formation/test_control.py` (add a reviewed-flag test)

**Interfaces:**
- Consumes: `Profile.control_requirement() -> dict | None` (Task 1).
- Produces: `control_progress(user) -> dict` now always includes `"reviewed": bool`. When unreviewed: `{"reviewed": False, "total_years": <float>}` (no `total_target`/`four_year`/`two_year`). When reviewed: adds `"reviewed": True` alongside the existing `total_years`/`total_target`/`four_year`/`two_year`.

- [ ] **Step 1: Write the failing test** — append to `formation/test_control.py`:

```python
def test_control_progress_unreviewed_has_no_target(db):
    import datetime as dt

    from accounts.models import Profile, User
    from formation.control import control_progress
    from formation.models import ControlAnalysis

    u = User.objects.create_user(email="unrev@example.com", password="x")
    u.profile.role = Profile.Role.PRE_CANDIDATE
    u.profile.formation_background = Profile.FormationBackground.UNREVIEWED
    u.profile.save()
    ControlAnalysis.objects.create(
        member=u, supervisor_name="S", requirement="four_year",
        start_date=dt.date.today() - dt.timedelta(days=int(365.25 * 2)),
    )

    prog = control_progress(u)
    assert prog["reviewed"] is False
    assert "total_target" not in prog
    assert prog["total_years"] == pytest.approx(2.0, abs=0.05)
```

(Ensure `import pytest` is present at the top of the file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest formation/test_control.py::test_control_progress_unreviewed_has_no_target -q`
Expected: FAIL — `KeyError: 'reviewed'`.

- [ ] **Step 3: Implement.** In `formation/control.py`, edit `control_progress` so it short-circuits when there is no requirement:

```python
def control_progress(user) -> dict:
    settings_ = FormationSettings.load()
    req = user.profile.control_requirement()
    entries = list(ControlAnalysis.objects.filter(member=user))
    total_years = round(sum((c.duration_years for c in entries), 0.0), 2)
    if req is None:
        return {"reviewed": False, "total_years": total_years}

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
    total_target = settings_.four_year_threshold + settings_.two_year_threshold * n_two
    return {
        "reviewed": True,
        "total_years": total_years,
        "total_target": total_target,
        "four_year": _slot(four[0] if four else None, settings_.four_year_threshold),
        "two_year": two_slots,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest formation/test_control.py -q`
Expected: PASS (all, including the reviewed ones — they now also carry `reviewed: True`).

- [ ] **Step 5: Commit**

```bash
git add formation/control.py formation/test_control.py
git commit -m "feat(formation): control_progress returns neutral payload when background unreviewed (task #466)"
```

---

### Task 3: `BackgroundDetermination` audit model

**Files:**
- Modify: `formation/models.py` (new model)
- Create: `formation/migrations/00XX_backgrounddetermination.py` (via `makemigrations`)
- Create: `formation/test_background.py` (model test)

**Interfaces:**
- Produces: `formation.models.BackgroundDetermination` with fields `member` (FK User, `related_name="background_determinations"`), `background` (CharField), `previous` (CharField, blank), `set_by` (FK User, nullable), `created_at` (auto), `note` (TextField, blank); `Meta.ordering = ["-created_at"]`.

- [ ] **Step 1: Write the failing test** — `formation/test_background.py`:

```python
import pytest

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_background_determination_records_change():
    from formation.models import BackgroundDetermination

    member = User.objects.create_user(email="m@example.com", password="x")
    setter = User.objects.create_user(email="a@example.com", password="x")
    row = BackgroundDetermination.objects.create(
        member=member, background="clinical", previous="unreviewed",
        set_by=setter, note="Licensed clinical psychologist.",
    )
    assert row.created_at is not None
    assert list(member.background_determinations.all()) == [row]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest formation/test_background.py -q`
Expected: FAIL — `ImportError: cannot import name 'BackgroundDetermination'`.

- [ ] **Step 3: Implement the model** in `formation/models.py`:

```python
class BackgroundDetermination(models.Model):
    """Immutable audit row: one per actual change to a student's
    ``Profile.formation_background``. The Profile holds the current
    (denormalized) value; this table is the history."""

    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="background_determinations",
    )
    background = models.CharField(max_length=12)
    previous = models.CharField(max_length=12, blank=True)
    set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.member} → {self.background} ({self.created_at:%Y-%m-%d})"
```

Ensure `from django.conf import settings` is imported at the top of `formation/models.py` (add it if missing).

- [ ] **Step 4: Make the migration and run tests**

Run: `uv run python manage.py makemigrations formation && uv run pytest formation/test_background.py -q`
Expected: creates `formation/migrations/00XX_backgrounddetermination.py`; test PASSES.

- [ ] **Step 5: Commit**

```bash
git add formation/models.py formation/migrations/ formation/test_background.py
git commit -m "feat(formation): BackgroundDetermination audit model (task #466)"
```

---

### Task 4: `FORMATION_BACKGROUND` notification category + wrapper

**Files:**
- Modify: `notifications/categories.py` (enum + `CATEGORY_META`)
- Modify: `formation/notifications.py` (`background_set` wrapper)
- Create: `formation/test_background_notify.py`

**Interfaces:**
- Produces: `notifications.categories.Category.FORMATION_BACKGROUND = "formation_background"`; `formation.notifications.background_set(member, row)` — rings the member's bell (in-app on by default, email off by default), linking to the Formation tab's control section.

- [ ] **Step 1: Write the failing test** — `formation/test_background_notify.py`:

```python
import pytest

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_background_set_notifies_member():
    from formation import notifications as notify_formation
    from formation.models import BackgroundDetermination
    from notifications.categories import Category
    from notifications.models import Notification

    member = User.objects.create_user(email="m@example.com", password="x")
    row = BackgroundDetermination.objects.create(
        member=member, background="clinical", previous="unreviewed",
    )
    notify_formation.background_set(member, row)

    n = Notification.objects.get(recipient=member, category=Category.FORMATION_BACKGROUND)
    assert "clinical" in n.title.lower()
    assert "#control" in n.url
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest formation/test_background_notify.py -q`
Expected: FAIL — `AttributeError: FORMATION_BACKGROUND` (or `background_set` missing).

- [ ] **Step 3: Implement.** In `notifications/categories.py`, add to the `Category` enum (in the Admissions block, after `EXTERNAL_CONTROL_ANALYST`):

```python
    FORMATION_BACKGROUND = "formation_background", _("Formation background")
```

And add to `CATEGORY_META` in the Account section (near `ACCOUNT_ADVISOR`):

```python
    _C.FORMATION_BACKGROUND: _M(
        SECTION_ACCOUNT, _("Formation background"),
        _("When the Meeting of Analysts or your advisor sets your control-"
          "analysis requirement (clinical or academic)."),
        default_email=_E.OFF,
    ),
```

In `formation/notifications.py`, add:

```python
def background_set(member, determination) -> None:
    from notifications.categories import Category

    label = {"clinical": "clinical", "academic": "academic"}.get(
        determination.background, determination.background
    )
    notify(
        member, Category.FORMATION_BACKGROUND,
        title=f"Your formation control requirement has been set to {label}",
        url=reverse("formation:formation") + "#control",
        target=determination,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest formation/test_background_notify.py notifications/ -q`
Expected: PASS (and existing notifications tests stay green — e.g. any "every category has meta" check now covers the new one).

- [ ] **Step 5: Commit**

```bash
git add notifications/categories.py formation/notifications.py formation/test_background_notify.py
git commit -m "feat(notifications): FORMATION_BACKGROUND category + background_set wrapper (task #466)"
```

---

### Task 5: `set_background` service (single write path)

**Files:**
- Create: `formation/background.py`
- Create: `formation/test_background_service.py`

**Interfaces:**
- Consumes: `BackgroundDetermination` (Task 3), `background_set` (Task 4), `Profile.formation_background` (Task 1).
- Produces: `formation.background.set_background(member, value, *, by, note="") -> BackgroundDetermination | None` — no-op (returns None, records nothing, no notify) when `value == member.profile.formation_background`; otherwise updates the profile, writes an audit row, notifies the member, returns the row.

- [ ] **Step 1: Write the failing test** — `formation/test_background_service.py`:

```python
import pytest

from accounts.models import Profile, User

pytestmark = pytest.mark.django_db


def _member():
    return User.objects.create_user(email="m@example.com", password="x")


def test_set_background_writes_row_updates_profile_and_notifies():
    from formation.background import set_background
    from formation.models import BackgroundDetermination
    from notifications.categories import Category
    from notifications.models import Notification

    member, setter = _member(), User.objects.create_user(email="a@example.com", password="x")
    row = set_background(member, Profile.FormationBackground.CLINICAL,
                         by=setter, note="Licensed clinician.")

    member.profile.refresh_from_db()
    assert member.profile.formation_background == Profile.FormationBackground.CLINICAL
    assert row.previous == Profile.FormationBackground.UNREVIEWED
    assert row.note == "Licensed clinician."
    assert BackgroundDetermination.objects.filter(member=member).count() == 1
    assert Notification.objects.filter(
        recipient=member, category=Category.FORMATION_BACKGROUND).exists()


def test_set_background_noop_when_unchanged():
    from formation.background import set_background
    from formation.models import BackgroundDetermination

    member = _member()
    member.profile.formation_background = Profile.FormationBackground.ACADEMIC
    member.profile.save()

    assert set_background(member, Profile.FormationBackground.ACADEMIC, by=None) is None
    assert BackgroundDetermination.objects.filter(member=member).count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest formation/test_background_service.py -q`
Expected: FAIL — `ModuleNotFoundError: formation.background`.

- [ ] **Step 3: Implement** `formation/background.py`:

```python
"""Single audited write path for a student's formation background."""

from __future__ import annotations

from . import notifications as notify_formation
from .models import BackgroundDetermination


def set_background(member, value, *, by, note="") -> BackgroundDetermination | None:
    """Set ``member``'s formation background to ``value`` (``clinical`` or
    ``academic``), recording an audit row and notifying the member. A no-op
    (returns None) when the value is unchanged."""
    profile = member.profile
    old = profile.formation_background
    if value == old:
        return None
    profile.formation_background = value
    profile.save(update_fields=["formation_background"])
    row = BackgroundDetermination.objects.create(
        member=member, background=value, previous=old, set_by=by,
        note=(note or "").strip(),
    )
    notify_formation.background_set(member, row)
    return row
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest formation/test_background_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add formation/background.py formation/test_background_service.py
git commit -m "feat(formation): set_background audited write-path service (task #466)"
```

---

### Task 6: Advisor surface — audited form replacing the checkbox

**Files:**
- Modify: `formation/views.py:843-856` (`advisee_set_background`)
- Modify: `formation/templates/formation/advisee_detail.html:62-95` (form + history; guard progress with `reviewed`)
- Modify: `formation/views.py` advisee_detail context (add `background_history`)
- Modify: `formation/test_advisor_view.py:65-83` (`test_advisor_sets_advisee_clinical_background`)

**Interfaces:**
- Consumes: `set_background` (Task 5), `control_progress.reviewed` (Task 2).
- Produces: `advisee_set_background` reads `request.POST["background"]` (`clinical`/`academic`) + `request.POST.get("note","")` and calls `set_background(advisee, value, by=request.user, note=note)`.

- [ ] **Step 1: Update the failing test** — replace `test_advisor_sets_advisee_clinical_background` in `formation/test_advisor_view.py`:

```python
def test_advisor_sets_advisee_background(client, db):
    advisor, advisee = _advisor_and_advisee()  # existing helper in this file
    client.force_login(advisor)
    resp = client.post(
        reverse("formation:advisee_set_background", args=[advisee.pk]),
        {"background": "clinical", "note": "Licensed clinician."},
    )
    assert resp.status_code in (302, 303)
    advisee.profile.refresh_from_db()
    from accounts.models import Profile
    assert advisee.profile.formation_background == Profile.FormationBackground.CLINICAL
    assert advisee.background_determinations.first().note == "Licensed clinician."
```

(Match the existing fixture/helper names in the file — reuse whatever builds an advisor+advisee there; the current test at line 65 shows the pattern.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest formation/test_advisor_view.py -q`
Expected: FAIL — posts `background` but the view still reads the old `clinical_background` checkbox.

- [ ] **Step 3: Implement the view.** Replace `advisee_set_background` (`formation/views.py:843-856`) body:

```python
@login_required
@require_POST
def advisee_set_background(request, pk):
    """Advisor (or staff) sets an advisee's formation background — audited."""
    from accounts.models import Profile, User

    from .background import set_background
    from .permissions import can_view_advisee

    advisee = get_object_or_404(User.objects.select_related("profile"), pk=pk)
    if not can_view_advisee(request.user, advisee):
        raise PermissionDenied
    value = request.POST.get("background")
    valid = {Profile.FormationBackground.CLINICAL, Profile.FormationBackground.ACADEMIC}
    if value not in valid:
        messages.error(request, "Choose clinical or academic.")
        return redirect("formation:advisee_detail", pk=advisee.pk)
    if set_background(advisee, value, by=request.user,
                      note=request.POST.get("note", "")):
        messages.success(request, "Background updated.")
    else:
        messages.info(request, "No change.")
    return redirect("formation:advisee_detail", pk=advisee.pk)
```

In the `advisee_detail` view (context near `formation/views.py:813`), add:

```python
"background_history": advisee.background_determinations.select_related("set_by")[:5],
```

- [ ] **Step 4: Implement the template.** In `advisee_detail.html`, replace the checkbox form (lines ~66-73) with:

```django
    <form method="post" action="{% url 'formation:advisee_set_background' advisee.pk %}" class="space-y-2 text-sm">
      {% csrf_token %}
      <div class="flex flex-wrap items-center gap-3">
        <label class="flex items-center gap-1">
          <input type="radio" name="background" value="clinical" class="radio radio-sm"
                 {% if advisee.profile.formation_background == "clinical" %}checked{% endif %}>
          Clinical (2: one 4-year, one 2-year)
        </label>
        <label class="flex items-center gap-1">
          <input type="radio" name="background" value="academic" class="radio radio-sm"
                 {% if advisee.profile.formation_background == "academic" %}checked{% endif %}>
          Academic (3: one 4-year, two 2-year)
        </label>
      </div>
      <input type="text" name="note" placeholder="Optional note (for the record)"
             class="input input-bordered input-sm w-full">
      <button class="btn btn-ghost btn-xs">Save background</button>
    </form>
    {% if advisee.profile.formation_background == "unreviewed" %}
    <p class="text-xs text-warning">Not yet determined by the Meeting of Analysts.</p>
    {% endif %}
    {% if background_history %}
    <details class="text-xs text-base-content/60">
      <summary class="cursor-pointer">History</summary>
      <ul class="mt-1 space-y-1">
        {% for h in background_history %}
        <li>{{ h.created_at|date:"M j, Y" }}: {{ h.get_background_display|default:h.background }}{% if h.set_by %}, by {{ h.set_by.get_full_name|default:h.set_by.email }}{% endif %}{% if h.note %} , {{ h.note }}{% endif %}</li>
        {% endfor %}
      </ul>
    </details>
    {% endif %}
```

Then wrap the progress+slots block that follows (the `<div class="space-y-1">` total-bar through the end of the 2-year `{% endfor %}`) in:

```django
    {% if control_progress.reviewed %}
    ... existing total bar + 4-year slot + 2-year slots ...
    {% else %}
    <p class="text-sm text-base-content/60">Control requirement will show once a background is set above.</p>
    {% endif %}
```

Note: `get_background_display` won't resolve (the audit row's `background` is a plain CharField with no choices); the template uses `|default:h.background` fallback, so it renders the raw value. That's acceptable for the advisor history line.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest formation/test_advisor_view.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add formation/views.py formation/templates/formation/advisee_detail.html formation/test_advisor_view.py
git commit -m "feat(formation): advisor sets background through audited form (task #466)"
```

---

### Task 7: Meeting-of-Analysts surface — list, set, history, landing card

**Files:**
- Modify: `formation/views.py` (`background_queue`, `background_detail`)
- Modify: `formation/urls.py` (two MoA routes)
- Create: `formation/templates/formation/background_queue.html`
- Create: `formation/templates/formation/background_detail.html`
- Modify: `core/staff.py:603-613` (`meeting_of_analysts_admin` context: `open_backgrounds`)
- Modify: `core/templates/core/staff/admin/meeting_of_analysts.html` (Backgrounds card)
- Create: `formation/test_background_moa.py`

**Interfaces:**
- Consumes: `_require_review` (admissions), `set_background` (Task 5), `Profile.IN_TRAINING_ROLES`, `Profile.FormationBackground`.
- Produces: URL names `formation:background_queue` (`/admin-tools/meeting-of-analysts/backgrounds/`) and `formation:background_detail` (`.../backgrounds/<int:pk>/`); a POST to `background_detail` sets the value via `set_background`.

- [ ] **Step 1: Write the failing test** — `formation/test_background_moa.py`:

```python
import pytest

from accounts.models import Profile, User

pytestmark = pytest.mark.django_db


def _analyst():
    u = User.objects.create_user(email="analyst@example.com", password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.formation_background = Profile.FormationBackground.CLINICAL
    u.profile.save()
    u.is_staff = True  # simplest reviewer gate; MoA membership also works
    u.save()
    return u


def _student(email="stu@example.com"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.PRE_CANDIDATE
    u.profile.save()
    return u


def test_queue_denied_to_plain_member(client):
    client.force_login(_student("nobody@example.com"))
    from django.urls import reverse
    assert client.get(reverse("formation:background_queue")).status_code == 403


def test_queue_lists_in_training_students(client):
    from django.urls import reverse
    _student("a@example.com")
    client.force_login(_analyst())
    resp = client.get(reverse("formation:background_queue"))
    assert resp.status_code == 200
    assert b"a@example.com" in resp.content


def test_moa_sets_background_with_note(client):
    from django.urls import reverse
    student = _student()
    client.force_login(_analyst())
    resp = client.post(
        reverse("formation:background_detail", args=[student.pk]),
        {"background": "clinical", "note": "CA-licensed."},
    )
    assert resp.status_code in (302, 303)
    student.profile.refresh_from_db()
    assert student.profile.formation_background == Profile.FormationBackground.CLINICAL
    assert student.background_determinations.first().note == "CA-licensed."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest formation/test_background_moa.py -q`
Expected: FAIL — `NoReverseMatch: 'background_queue'`.

- [ ] **Step 3: Implement views** in `formation/views.py`:

```python
@login_required
def background_queue(request):
    """Meeting of Analysts: in-training students and their formation background,
    unreviewed first."""
    _require_review(request)
    from django.db.models import Case, IntegerField, Value, When

    from accounts.models import Profile

    students = (
        Profile.objects.filter(role__in=Profile.IN_TRAINING_ROLES)
        .select_related("user")
        .annotate(_unrev=Case(
            When(formation_background=Profile.FormationBackground.UNREVIEWED, then=Value(0)),
            default=Value(1), output_field=IntegerField(),
        ))
        .order_by("_unrev", "user__last_name", "user__first_name", "user__email")
    )
    return render(request, "formation/background_queue.html", {
        "students": students,
        "unreviewed_value": Profile.FormationBackground.UNREVIEWED,
    })


@login_required
@require_POST
def background_detail(request, pk):
    """Meeting of Analysts sets one student's background (audited)."""
    _require_review(request)
    from accounts.models import Profile, User

    from .background import set_background

    student = get_object_or_404(User.objects.select_related("profile"), pk=pk)
    value = request.POST.get("background")
    valid = {Profile.FormationBackground.CLINICAL, Profile.FormationBackground.ACADEMIC}
    if value not in valid:
        messages.error(request, "Choose clinical or academic.")
    elif set_background(student, value, by=request.user, note=request.POST.get("note", "")):
        messages.success(request, f"Set {student.get_full_name() or student.email} to {value}.")
    else:
        messages.info(request, "No change.")
    return redirect("formation:background_queue")
```

Add routes to `formation/urls.py` (in the MoA block, using the `_MOA` prefix):

```python
    path(f"{_MOA}/backgrounds/", views.background_queue, name="background_queue"),
    path(f"{_MOA}/backgrounds/<int:pk>/", views.background_detail, name="background_detail"),
```

- [ ] **Step 4: Implement templates.** Create `formation/templates/formation/background_queue.html`:

```django
{% extends "base.html" %}
{% block content %}
<div class="mx-auto max-w-3xl px-4 py-8 space-y-6">
  <nav class="text-sm"><a href="{% url 'meeting_of_analysts_admin' %}" class="link link-hover text-base-content/60">← Meeting of Analysts Admin</a></nav>
  <h1 class="font-serif text-2xl">Formation backgrounds</h1>
  <p class="text-sm text-base-content/70">Set each in-training student's background, which determines their control-analysis requirement (clinical: one 4-year and one 2-year; academic: one 4-year and two 2-year). Students not yet reviewed are listed first.</p>
  <ul class="space-y-3">
    {% for p in students %}
    <li class="rounded-xl border border-base-300 p-4 space-y-2">
      <div class="flex items-center justify-between gap-2">
        <span class="font-medium">{{ p.user.get_full_name|default:p.user.email }}</span>
        {% if p.formation_background == unreviewed_value %}
        <span class="badge badge-warning badge-sm">unreviewed</span>
        {% else %}
        <span class="badge badge-ghost badge-sm">{{ p.get_formation_background_display }}</span>
        {% endif %}
      </div>
      <form method="post" action="{% url 'formation:background_detail' p.user.pk %}" class="flex flex-wrap items-center gap-3 text-sm">
        {% csrf_token %}
        <label class="flex items-center gap-1"><input type="radio" name="background" value="clinical" class="radio radio-sm" {% if p.formation_background == "clinical" %}checked{% endif %}> Clinical</label>
        <label class="flex items-center gap-1"><input type="radio" name="background" value="academic" class="radio radio-sm" {% if p.formation_background == "academic" %}checked{% endif %}> Academic</label>
        <input type="text" name="note" placeholder="Optional note" class="input input-bordered input-sm flex-1 min-w-40">
        <button class="btn btn-primary btn-sm">Save</button>
      </form>
    </li>
    {% empty %}
    <li class="text-sm text-base-content/60">No in-training students.</li>
    {% endfor %}
  </ul>
</div>
{% endblock %}
```

Create a minimal `formation/templates/formation/background_detail.html` (the POST redirects to the queue, but a template avoids a missing-template error if a GET is ever wired):

```django
{% extends "base.html" %}
{% block content %}
<div class="mx-auto max-w-3xl px-4 py-8">
  <a href="{% url 'formation:background_queue' %}" class="link">← Formation backgrounds</a>
</div>
{% endblock %}
```

In `core/staff.py::meeting_of_analysts_admin`, add to the imports/queries and context:

```python
from accounts.models import Profile
...
"open_backgrounds": Profile.objects.filter(
    role__in=Profile.IN_TRAINING_ROLES,
    formation_background=Profile.FormationBackground.UNREVIEWED,
).count(),
```

In `core/templates/core/staff/admin/meeting_of_analysts.html`, add a card (after the external-analysts include):

```django
  {% url 'formation:background_queue' as backgrounds_url %}
  {% include "core/staff/admin/_section.html" with title="Formation backgrounds" body="Set each in-training student's background (clinical or academic), which determines their control-analysis requirement. Students not yet reviewed are counted here." link=backgrounds_url link_label="Review backgrounds" count=open_backgrounds count_label="unreviewed" %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest formation/test_background_moa.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add formation/views.py formation/urls.py formation/templates/formation/background_queue.html formation/templates/formation/background_detail.html core/staff.py core/templates/core/staff/admin/meeting_of_analysts.html formation/test_background_moa.py
git commit -m "feat(formation): Meeting-of-Analysts formation-background surface (task #466)"
```

---

### Task 8: Student tracker — neutral state when unreviewed

**Files:**
- Modify: `formation/templates/formation/_tab_formation.html:175-205` (guard the progress block with `reviewed`)
- Create/append: `formation/test_control_views.py` (a rendering test)

**Interfaces:**
- Consumes: `control_progress.reviewed` (Task 2).

- [ ] **Step 1: Write the failing test** — add to `formation/test_control_views.py` (create if absent, following the file's existing client/login pattern):

```python
def test_formation_tab_shows_neutral_when_unreviewed(client, db):
    from django.urls import reverse

    from accounts.models import Profile, User

    u = User.objects.create_user(email="stu@example.com", password="x")
    u.profile.role = Profile.Role.PRE_CANDIDATE
    u.profile.formation_background = Profile.FormationBackground.UNREVIEWED
    u.profile.save()
    client.force_login(u)

    resp = client.get(reverse("formation:formation"))
    assert resp.status_code == 200
    assert b"Meeting of Analysts" in resp.content  # neutral copy
    assert b"total years across your control analyses" not in resp.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest formation/test_control_views.py::test_formation_tab_shows_neutral_when_unreviewed -q`
Expected: FAIL — the target bar renders regardless of state.

- [ ] **Step 3: Implement.** In `_tab_formation.html`, wrap the total bar + 4-year slot + 2-year slots (the `<div class="space-y-1">` at ~line 175 through the closing of the 2-year `{% endfor %}` block at ~line 204) in:

```django
      {% if control_progress.reviewed %}
      <div class="space-y-1">
        <progress class="progress progress-primary w-full" value="{{ control_progress.total_years }}" max="{{ control_progress.total_target }}"></progress>
        <p class="text-sm text-base-content/70">{{ control_progress.total_years|floatformat:1 }} of {{ control_progress.total_target }} total years across your control analyses.</p>
      </div>
      <div class="space-y-3">
        ... existing 4-year slot + 2-year slots unchanged ...
      </div>
      {% else %}
      <p class="text-sm text-base-content/70">Your control-analysis requirement will be set by the Meeting of Analysts. You can still log your control analyses below.</p>
      {% endif %}
```

(Keep the `{% if control_entries %}` log list that follows outside/after this guard, so entries always show.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest formation/test_control_views.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add formation/templates/formation/_tab_formation.html formation/test_control_views.py
git commit -m "feat(formation): neutral tracker state while background unreviewed (task #466)"
```

---

### Task 9: Full-suite green + lint

**Files:** none (verification).

- [ ] **Step 1: Grep for stragglers**

Run: `git grep -n clinical_background -- ':!docs/'`
Expected: no results (all references migrated). If any remain in code/templates/tests, fix them.

- [ ] **Step 2: Run the full suite + lint + migration check**

Run: `uv run pytest -q && uv run ruff check . && uv run python manage.py makemigrations --check --dry-run`
Expected: all PASS; `No changes detected`.

- [ ] **Step 3: Commit any fixes**

```bash
git add -A && git commit -m "chore(formation): migrate remaining clinical_background references (task #466)" || echo "nothing to commit"
```

---

## Self-Review

**Spec coverage:** 3-state field + requirement (T1) ✓; neutral progress payload (T2) ✓; audit model (T3) ✓; notification category + wrapper (T4) ✓; shared `set_background` service with no-op (T5) ✓; advisor audited surface (T6) ✓; MoA surface + landing count + history (T7) ✓; student tracker neutral state (T8) ✓; data migration True→CLINICAL / False→UNREVIEWED (T1) ✓; notify-on-change (T4/T5) ✓; testing across all (each task) ✓; full-suite verification (T9) ✓.

**Placeholder scan:** `00XX` migration filenames are produced by `makemigrations` (real command given), not placeholders. No TBD/TODO/"add error handling" left.

**Type consistency:** `formation_background` values `unreviewed`/`clinical`/`academic` used consistently; `set_background(member, value, *, by, note="")` signature matches all callers (T6, T7); `control_progress` `reviewed` key consumed in T6 (advisee) and T8 (tab); `background_set(member, row)` matches its call in T5.
