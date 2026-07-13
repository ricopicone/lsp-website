# Shared School Officers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Board's Chair/Co-chair roster the single source of truth for the President/Vice President, auto-syncing the President/Vice-President `StaffRole`s and surfacing the same officers as leaders on the Meeting of Analysts workspace roster.

**Architecture:** A `post_save`/`post_delete` signal on `workgroups.WorkgroupMembership` recomputes the two officer `StaffRole`s from the Board committee's serving Chair/Co-chair (`committees.officers.sync_school_officers`). The Meeting of Analysts roster derives its President/Vice President leader rows from those synced StaffRoles. Board → Appointments stops managing the two officer roles.

**Tech Stack:** Django 5.2, pytest-django. SQLite (dev). Existing apps `committees`, `workgroups`, `core`.

## Global Constraints

- Do **not** touch the shared `WorkgroupMembership.Role` enum — President/Vice President are a display/StaffRole concern, not new roles (tasks #368, #428).
- Board roster → StaffRole sync is **one-directional**. The StaffRole is a mirror.
- The Programming Committee Chair stays displayed as "Chair" — unchanged. Only the Board (slug `board`) and the Meeting of Analysts (slug `meeting-of-analysts`) are officer bodies.
- Member-facing copy uses UNSPACED em dashes only in docs/admin; site copy prefers commas (existing project rule) — but these are admin templates, so match surrounding style.
- Keep pytest and ruff green.

---

### Task 1: `sync_school_officers()` + signal + reconcile migration

**Files:**
- Create: `committees/officers.py`
- Create: `committees/signals.py`
- Modify: `committees/apps.py` (add `ready()`)
- Create: `committees/migrations/0010_reconcile_school_officers.py`
- Test: `committees/tests.py` (append)

**Interfaces:**
- Produces: `committees.officers.sync_school_officers() -> None` — recomputes `StaffRole.PRESIDENT` holders = Board serving Chairs, `StaffRole.VICE_PRESIDENT` holders = Board serving Co-chairs. Idempotent.

- [ ] **Step 1: Write the failing test**

Append to `committees/tests.py`:

```python
@pytest.mark.django_db
def test_board_chair_syncs_president_staffrole():
    """Task #428 follow-on: setting the Board's Chair/Co-chair drives the
    President / Vice-President StaffRole holders (single source of truth)."""
    from core.models import StaffRole
    from workgroups.models import WorkgroupMembership

    board = Committee.objects.get(slug="board")
    pres = User.objects.create_user(email="p@x.test", first_name="Pat", last_name="Prez")
    veep = User.objects.create_user(email="v@x.test", first_name="Val", last_name="Veep")

    board.add_member(pres, role=WorkgroupMembership.Role.CHAIR, start_date=date(2026, 1, 1))
    board.add_member(veep, role=WorkgroupMembership.Role.CO_CHAIR, start_date=date(2026, 1, 1))

    assert set(StaffRole.objects.get(key=StaffRole.PRESIDENT).holders.all()) == {pres}
    assert set(StaffRole.objects.get(key=StaffRole.VICE_PRESIDENT).holders.all()) == {veep}


@pytest.mark.django_db
def test_removing_board_chair_clears_president_and_pc_chair_ignored():
    """Ending the Chair membership empties President; a Programming Committee
    Chair never touches the officer StaffRoles."""
    from core.models import StaffRole
    from workgroups.models import WorkgroupMembership

    board = Committee.objects.get(slug="board")
    pc = Committee.objects.get(slug="programming-committee")
    pres = User.objects.create_user(email="p2@x.test", first_name="Pat", last_name="Prez")
    veep = User.objects.create_user(email="v2@x.test", first_name="Val", last_name="Veep")
    conv = User.objects.create_user(email="c@x.test", first_name="Con", last_name="Vener")

    # Two leads so removing the Chair doesn't hit the sole-lead orphan guard.
    board.add_member(pres, role=WorkgroupMembership.Role.CHAIR, start_date=date(2026, 1, 1))
    board.add_member(veep, role=WorkgroupMembership.Role.CO_CHAIR, start_date=date(2026, 1, 1))
    pc.add_member(conv, role=WorkgroupMembership.Role.CHAIR, start_date=date(2026, 1, 1))
    assert set(StaffRole.objects.get(key=StaffRole.PRESIDENT).holders.all()) == {pres}

    assert board.workgroup.remove_member(pres) is True  # end-dates the row
    assert StaffRole.objects.get(key=StaffRole.PRESIDENT).holders.count() == 0
    # Co-chair (Vice President) untouched; the PC chair was never an officer.
    assert set(StaffRole.objects.get(key=StaffRole.VICE_PRESIDENT).holders.all()) == {veep}
    assert conv not in StaffRole.objects.get(key=StaffRole.VICE_PRESIDENT).holders.all()
```

Ensure the top of `committees/tests.py` has `from datetime import date`, `import pytest`, `from accounts.models import User`, `from committees.models import Committee` (add any missing).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest committees/tests.py::test_board_chair_syncs_president_staffrole -q`
Expected: FAIL (President holders empty — no sync wired yet).

- [ ] **Step 3: Create `committees/officers.py`**

```python
"""School officers (President / Vice-President) derived from the Board roster.

The Board committee's serving Chair / Co-chair ARE the school's President /
Vice-President. This module keeps the two ``core.StaffRole`` rows in lockstep
with that roster (one-directional: roster -> StaffRole), so the Board's Settings
roster is the single place officers are set. See
docs/superpowers/specs/2026-07-12-shared-school-officers-design.md.
"""

from __future__ import annotations


def sync_school_officers() -> None:
    """President holders := Board serving Chairs; Vice-President holders :=
    Board serving Co-chairs. Idempotent — recomputed and ``.set()`` each call."""
    from committees.models import Committee
    from core.models import StaffRole
    from workgroups.models import WorkgroupMembership

    board = (
        Committee.objects.filter(slug="board").select_related("workgroup").first()
    )
    if board is None or board.workgroup_id is None:
        return
    serving = list(board.workgroup.memberships.serving().select_related("user"))
    mapping = {
        WorkgroupMembership.Role.CHAIR: StaffRole.PRESIDENT,
        WorkgroupMembership.Role.CO_CHAIR: StaffRole.VICE_PRESIDENT,
    }
    for role_value, key in mapping.items():
        holders = [m.user for m in serving if m.role == role_value]
        role = StaffRole.objects.filter(key=key).first()
        if role is not None:
            role.holders.set(holders)
```

- [ ] **Step 4: Create `committees/signals.py`**

```python
"""Keep the school officers synced whenever the Board roster changes."""

from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from workgroups.models import WorkgroupMembership

from .officers import sync_school_officers

_OFFICER_ROLES = {WorkgroupMembership.Role.CHAIR, WorkgroupMembership.Role.CO_CHAIR}


@receiver(post_save, sender=WorkgroupMembership)
@receiver(post_delete, sender=WorkgroupMembership)
def _sync_school_officers_on_board_change(sender, instance, **kwargs):
    # Cheap gate first: only Chair/Co-chair rows can change officers.
    if instance.role not in _OFFICER_ROLES:
        return
    try:
        committee = instance.workgroup.committee
    except ObjectDoesNotExist:
        return
    if committee.slug != "board":
        return
    sync_school_officers()
```

- [ ] **Step 5: Wire the signal in `committees/apps.py`**

```python
from django.apps import AppConfig


class CommitteesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "committees"

    def ready(self):
        from . import signals  # noqa: F401
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest committees/tests.py::test_board_chair_syncs_president_staffrole committees/tests.py::test_removing_board_chair_clears_president_and_pc_chair_ignored -q`
Expected: PASS (2 passed).

- [ ] **Step 7: Create the reconcile migration**

`committees/migrations/0010_reconcile_school_officers.py`:

```python
"""One-time reconcile: point the President / Vice-President StaffRoles at the
Board's current Chair / Co-chair (task #428 follow-on). Idempotent."""

from __future__ import annotations

from django.db import migrations
from django.db.models import Q


def reconcile(apps, schema_editor):
    from django.utils import timezone

    Committee = apps.get_model("committees", "Committee")
    StaffRole = apps.get_model("core", "StaffRole")

    board = (
        Committee.objects.filter(slug="board").select_related("workgroup").first()
    )
    if board is None or board.workgroup_id is None:
        return
    today = timezone.localdate()
    serving = board.workgroup.memberships.filter(
        Q(end_date__isnull=True) | Q(end_date__gt=today)
    )
    mapping = {"chair": "president", "co_chair": "vice_president"}
    for role_value, key in mapping.items():
        holders = [m.user for m in serving if m.role == role_value]
        role = StaffRole.objects.filter(key=key).first()
        if role is not None:
            role.holders.set(holders)


class Migration(migrations.Migration):
    dependencies = [
        ("committees", "0009_meeting_of_analysts_auto_member"),
        ("core", "0012_seed_president_vice_president"),
        ("workgroups", "0025_meetingseries_timezone"),
    ]
    operations = [migrations.RunPython(reconcile, migrations.RunPython.noop)]
```

- [ ] **Step 8: Verify migration applies cleanly**

Run: `uv run python manage.py migrate committees -v0 && uv run python manage.py makemigrations --check --dry-run`
Expected: migrate succeeds; "No changes detected".

- [ ] **Step 9: Commit**

```bash
git add committees/officers.py committees/signals.py committees/apps.py committees/migrations/0010_reconcile_school_officers.py committees/tests.py
git commit -m "feat(officers): sync President/VP StaffRole from Board roster (task #428)"
```

---

### Task 2: Meeting of Analysts shows President/VP as leader chips

**Files:**
- Modify: `workgroups/models.py` (the `Participant` dataclass ~lines 93-112; `Workgroup.participants()` ~lines 388-454)
- Test: `workgroups/tests.py` (append)

**Interfaces:**
- Consumes: `StaffRole.PRESIDENT` / `VICE_PRESIDENT` holders (synced by Task 1).
- Produces: `Participant.officer_title: str | None` — explicit display label for a derived officer row; `Participant.role_label` prefers it.

- [ ] **Step 1: Write the failing test**

Append to `workgroups/tests.py`:

```python
@pytest.mark.django_db
def test_moa_roster_shows_president_and_vp_as_leaders(client):
    """Task #428 follow-on: the Meeting of Analysts workspace roster surfaces
    the synced President / Vice President as leaders, derived from the shared
    appointment; a plain analyst stays a Member."""
    from committees.models import Committee
    from core.models import StaffRole

    moa = Committee.objects.get(slug="meeting-of-analysts")
    wg = moa.workgroup
    wg.landing_visibility = Visibility.PUBLIC
    wg.save(update_fields=["landing_visibility"])

    pres = _user("pres@x.test", role=Profile.Role.ANALYST, first="Pat", last="Prez")
    plain = _user("plain@x.test", role=Profile.Role.ANALYST, first="Ana", last="Lyst")
    StaffRole.objects.get(key=StaffRole.PRESIDENT).holders.add(pres)

    roster = wg.participants()
    by_email = {p.user.email: p for p in roster}
    assert by_email["pres@x.test"].is_lead is True
    assert by_email["pres@x.test"].role_label == "President"
    assert by_email["plain@x.test"].is_lead is False

    body = client.get(wg.get_absolute_url()).content.decode()
    assert "President" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest workgroups/tests.py::test_moa_roster_shows_president_and_vp_as_leaders -q`
Expected: FAIL (`Participant` has no `officer_title`; President appears as a plain Member).

- [ ] **Step 3: Add `officer_title` to the `Participant` dataclass**

In `workgroups/models.py`, update the `Participant` dataclass fields and `role_label`:

```python
    user: object
    role: str
    is_lead: bool = False
    membership: object = None
    officer_title: str | None = None

    def get_role_display(self) -> str:
        try:
            return WorkgroupMembership.Role(self.role).label
        except ValueError:
            return self.role.replace("_", " ").title()

    @property
    def role_label(self) -> str:
        """Human role label with per-body officer titles applied (the Board's
        Chair / Co-chair read President / Vice President — tasks #368, #428).
        A derived officer row (no membership) carries an explicit
        ``officer_title``; stored participants defer to their membership's
        ``role_label``; other derived rows carry no officer title."""
        if self.officer_title:
            return self.officer_title
        if self.membership is not None:
            return self.membership.role_label
        return self.get_role_display()
```

- [ ] **Step 4: Inject the officers in `participants()`**

In `workgroups/models.py`, inside `Workgroup.participants()`, immediately **after** the `auto_member_role` block (the loop that adds derived `Member` rows, ending ~line 422) and **before** the `derived_events` block, add:

```python
        # The Meeting of Analysts' leaders are the school officers (President /
        # Vice-President), synced from the Board roster (task #428). Surface them
        # as leads here — overwriting their plain auto-member row — reusing the
        # Chair / Co-chair role values so they rank first, with an explicit
        # officer title for display.
        if self.auto_member_role:
            try:
                is_moa = self.committee.slug == "meeting-of-analysts"
            except ObjectDoesNotExist:
                is_moa = False
            if is_moa:
                from core.models import StaffRole

                officer_rows = [
                    (StaffRole.PRESIDENT, WorkgroupMembership.Role.CHAIR, "President"),
                    (StaffRole.VICE_PRESIDENT, WorkgroupMembership.Role.CO_CHAIR,
                     "Vice President"),
                ]
                for key, role_value, title in officer_rows:
                    sr = StaffRole.objects.filter(key=key).first()
                    if sr is None:
                        continue
                    for u in sr.holders.all():
                        seen[u.pk] = Participant(
                            user=u, role=role_value, is_lead=True,
                            officer_title=title,
                        )
```

`ObjectDoesNotExist` is already imported at the top of `workgroups/models.py`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest workgroups/tests.py::test_moa_roster_shows_president_and_vp_as_leaders -q`
Expected: PASS.

- [ ] **Step 6: Run the workgroups + committees suites (guard against roster regressions)**

Run: `uv run pytest workgroups/tests.py committees/tests.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add workgroups/models.py workgroups/tests.py
git commit -m "feat(officers): show President/VP as leaders on the MoA roster (task #428)"
```

---

### Task 3: Board → Appointments drops President/VP; officer note copy

**Files:**
- Modify: `core/staff.py` (`board_appointments`, ~lines 389-431)
- Modify: `core/templates/core/staff/admin/_officers.html` (note line)
- Modify: `core/templates/core/staff/admin/board_appointments.html` (note paragraph, ~lines 78-84)
- Test: `core/tests.py` (append)

**Interfaces:**
- Consumes: `StaffRole.PRESIDENT` / `VICE_PRESIDENT` constants.

- [ ] **Step 1: Write the failing test**

Append to `core/tests.py`:

```python
@pytest.mark.django_db
def test_appointments_omits_president_and_vice_president(client):
    """Task #428 follow-on: President / Vice President are set via the Board
    Settings roster, so Appointments no longer lists them, and posting those
    keys is rejected."""
    from core.models import StaffRole
    from accounts.models import User

    boss = User.objects.create_user(email="boss@x.test", is_staff=True, is_superuser=True)
    client.force_login(boss)

    body = client.get(reverse("board_appointments")).content.decode()
    assert "Treasurer" in body            # other roles still listed
    # President / Vice President are no longer appointable options here
    # (the note paragraph may mention them, so assert on the form values).
    assert 'value="president"' not in body
    assert 'value="vice_president"' not in body

    target = User.objects.create_user(email="t@x.test")
    resp = client.post(reverse("board_appointments"), {
        "action": "appoint", "role": StaffRole.PRESIDENT, "user": target.pk,
    })
    assert resp.status_code in (200, 302)
    assert target not in StaffRole.objects.get(key=StaffRole.PRESIDENT).holders.all()
```

Ensure `core/tests.py` imports `reverse` (`from django.urls import reverse`) and `pytest`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest core/tests.py::test_appointments_omits_president_and_vice_president -q`
Expected: FAIL (President/VP still listed and appointable).

- [ ] **Step 3: Exclude the officer roles in `board_appointments`**

In `core/staff.py`, in `board_appointments`:

Guard the POST so the officer keys can't be appointed here — after resolving `role`:

```python
        action = request.POST.get("action")
        role = StaffRole.objects.filter(key=request.POST.get("role")).first()
        member = User.objects.filter(pk=request.POST.get("user")).first()
        if role is not None and role.key in (StaffRole.PRESIDENT, StaffRole.VICE_PRESIDENT):
            messages.error(
                request,
                "President and Vice President are set in the Board's Settings roster "
                "(Chair and Co-chair).",
            )
            return redirect("board_appointments")
```

And filter them out of the listed `roles`:

```python
    roles = list(
        StaffRole.objects
        .exclude(key__in=[StaffRole.PRESIDENT, StaffRole.VICE_PRESIDENT])
        .prefetch_related("holders")
        .order_by("name")
    )
```

- [ ] **Step 4: Update `_officers.html` note**

In `core/templates/core/staff/admin/_officers.html`, change the trailing `<p>`:

```html
  <p class="text-xs text-base-content/40 mt-2">Set in the Board's Settings roster (Chair is President, Co-chair is Vice President); governs the Board and the Meeting of Analysts both.</p>
```

- [ ] **Step 5: Update `board_appointments.html` note**

In `core/templates/core/staff/admin/board_appointments.html`, replace the note paragraph (~lines 78-84) with:

```html
  <p class="text-xs text-base-content/50">
    Committee chairs and officers are roster roles — set those in each
    committee's workspace from <a href="{% url 'board_committees' %}" class="link">Committees</a>.
    The <strong>President</strong> and <strong>Vice President</strong> are the Board's
    Chair and Co-chair — set them in the Board's workspace under Settings → Members &amp; roles.
    The <strong>Applications Coordinator</strong> is appointed on the Meeting of
    Analysts' workspace under Settings → Members &amp; roles.
  </p>
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest core/tests.py::test_appointments_omits_president_and_vice_president -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add core/staff.py core/templates/core/staff/admin/_officers.html core/templates/core/staff/admin/board_appointments.html core/tests.py
git commit -m "feat(officers): move President/VP out of Appointments into Board Settings (task #428)"
```

---

### Task 4: Full-suite verification

- [ ] **Step 1: Run the whole suite**

Run: `uv run pytest -q`
Expected: all pass (no regressions in directory/about/officer tests).

- [ ] **Step 2: Lint**

Run: `uv run ruff check committees/ workgroups/ core/`
Expected: clean (pre-existing `accounts/test_advisor.py` issue is out of scope; do not touch it).

- [ ] **Step 3: Manual render check (verification-before-completion)**

Drive the real flow with a throwaway test or shell: create a Board Chair, assert the President StaffRole holder updates, and GET `/groups/meeting-of-analysts/` to confirm the President chip renders. Delete the throwaway after.

- [ ] **Step 4: Update the in-repo status log**

Add a short entry to `CLAUDE.md` (project status) noting the shared-officer sync, and add/update a memory entry (`board-officer-titles`) to mention the Board→StaffRole sync + MoA derivation.
