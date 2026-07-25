# Retired — Directory Indicator + Formation-Duty Exclusion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a "Retired" marker in the directory, and make retired members ineligible for formation duties by gating the two role-only surfaces (analyst availability, Meeting of Analysts) on active standing.

**Architecture:** Retired members are already excluded from advisor/control-analyst/interviewer pools (those require `standing == ACTIVE`). This closes the two remaining leaks with the same active-standing rule, plus adds an informational directory marker. Meeting-of-Analysts membership is role-derived through the generic `Workgroup.auto_member_role` mechanism (only the Meeting of Analysts uses it today), so the gate goes there.

**Tech Stack:** Django 5.2, pytest-django, Tailwind v4 + DaisyUI (template marker).

## Global Constraints

- `Profile.Standing` values: active / on_leave / resigned / emeritus / retired / removed. `Profile.deceased_on` is orthogonal (deceased ⇒ `user.is_active=False`).
- **Formation eligibility = `standing == ACTIVE`** everywhere (the uniform rule). The complete "active participant" gate is `profile__role=…, profile__standing=Profile.Standing.ACTIVE, is_active=True, profile__is_persona=False` — note `is_active=True` is required to also exclude deceased members (whose standing may still read `active`).
- Member-facing copy uses **commas, not em dashes**. Use **DaisyUI semantic tokens** (`text-base-content/60`, …), never hardcoded colors. Any Tailwind class must appear in a `.html`.
- Tests: pytest-django, `@pytest.mark.django_db`, `User.objects.create_user(email=...)` auto-creates the Profile. Keep the suite green (`uv run pytest`, `uv run ruff check .`).
- Edit files at the worktree path `/Users/picone/LSP-Web-Coordinator/lsp-website/.claude-worktrees/silver-quartz`, not the main repo.

---

### Task 1: Directory "Retired" indicator

**Files:**
- Modify: `accounts/models.py` (add `is_retired` property next to `is_deceased` ~line 502)
- Modify: `accounts/templates/accounts/directory.html` (card marker, near the `is_deceased` block ~line 44)
- Modify: `accounts/templates/accounts/directory_detail.html` (detail marker, near ~line 23)
- Test: `accounts/tests.py`

**Interfaces:**
- Produces: `Profile.is_retired -> bool` (`standing == Standing.RETIRED`); a "Retired" marker rendered when `is_retired and not is_deceased`.

- [ ] **Step 1: Write the failing tests**

Add to `accounts/tests.py`:

```python
@pytest.mark.django_db
def test_is_retired_property():
    u = User.objects.create_user(email="rtd@example.com")
    u.profile.standing = Profile.Standing.RETIRED
    u.profile.save()
    assert u.profile.is_retired is True
    u.profile.standing = Profile.Standing.ACTIVE
    u.profile.save()
    assert u.profile.is_retired is False


@pytest.mark.django_db
def test_directory_shows_retired_marker(client):
    u = User.objects.create_user(email="rtdir@example.com", first_name="Rhea", last_name="Tired")
    u.profile.role = Profile.Role.ANALYST
    u.profile.public = True
    u.profile.standing = Profile.Standing.RETIRED
    u.profile.save()
    resp = client.get(f"/directory/{u.profile.directory_slug}/")
    assert resp.status_code == 200
    assert "Retired" in resp.content.decode()


@pytest.mark.django_db
def test_directory_active_member_has_no_retired_marker(client):
    u = User.objects.create_user(email="act@example.com", first_name="Ann", last_name="Active")
    u.profile.role = Profile.Role.ANALYST
    u.profile.public = True
    u.profile.save()
    resp = client.get(f"/directory/{u.profile.directory_slug}/")
    body = resp.content.decode()
    # The word may appear in nav/other copy; assert the marker element text isn't present.
    assert "Retired</span>" not in body and "Retired</p>" not in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest accounts/tests.py -k "is_retired or retired_marker or no_retired_marker" -q`
Expected: FAIL (`AttributeError: is_retired` / marker absent).

- [ ] **Step 3: Add the `is_retired` property**

In `accounts/models.py`, next to `is_deceased` (~line 502):

```python
    @property
    def is_retired(self) -> bool:
        return self.standing == self.Standing.RETIRED
```

- [ ] **Step 4: Add the card marker**

In `accounts/templates/accounts/directory.html`, next to the existing `is_deceased` block (~line 44), add (deceased takes precedence):

```html
            {% if p.is_retired and not p.is_deceased %}
            <div><span class="text-xs text-base-content/60 italic">Retired</span></div>
            {% endif %}
```

- [ ] **Step 5: Add the detail marker**

In `accounts/templates/accounts/directory_detail.html`, next to the `is_deceased` marker (~line 23), add:

```html
      {% if profile.is_retired and not profile.is_deceased %}
      <p class="text-sm text-base-content/60 italic mt-1">Retired</p>
      {% endif %}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest accounts/tests.py -k "is_retired or retired_marker or no_retired_marker" -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add accounts/models.py accounts/templates/accounts/directory.html accounts/templates/accounts/directory_detail.html accounts/tests.py
git commit -m "feat(accounts): 'Retired' marker in the directory (task #451)"
```

---

### Task 2: Analyst availability — active-standing gate

**Files:**
- Modify: `availability/services.py:eligible_profiles()` (~line 54-62)
- Test: the availability test module (find it — likely `availability/tests.py` or `availability/test_*.py`)

**Interfaces:**
- Consumes: `Profile.Standing.ACTIVE`.
- Produces: `eligible_profiles()` returns only active-standing, active-account, non-persona analysts.

- [ ] **Step 1: Locate the availability test module**

Run: `ls availability/ | grep -i test`
Note the file to add the test to (use its existing fixture/import style).

- [ ] **Step 2: Write the failing test**

Add to the availability test module (adapt imports to the file's style):

```python
import pytest

from accounts.models import Profile, User
from availability.services import eligible_profiles


@pytest.mark.django_db
def test_eligible_profiles_excludes_retired_and_deceased():
    active = User.objects.create_user(email="av-active@example.com")
    active.profile.role = Profile.Role.ANALYST
    active.profile.save()

    retired = User.objects.create_user(email="av-retired@example.com")
    retired.profile.role = Profile.Role.ANALYST
    retired.profile.standing = Profile.Standing.RETIRED
    retired.profile.save()

    from datetime import date
    deceased = User.objects.create_user(email="av-deceased@example.com")
    deceased.profile.role = Profile.Role.ANALYST
    deceased.profile.deceased_on = date(2026, 7, 23)  # sets is_active=False
    deceased.profile.save()

    ids = set(eligible_profiles().values_list("user_id", flat=True))
    assert active.id in ids
    assert retired.id not in ids
    assert deceased.id not in ids
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest availability/ -k eligible_profiles_excludes_retired -q`
Expected: FAIL (retired/deceased currently included).

- [ ] **Step 4: Add the active-standing gate**

In `availability/services.py:eligible_profiles()`, change the return queryset:

```python
    from accounts.models import Profile

    return Profile.objects.filter(
        role__in=AVAILABILITY_ROLES,
        standing=Profile.Standing.ACTIVE,
        is_persona=False,
        user__is_active=True,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest availability/ -k eligible_profiles_excludes_retired -q`
Expected: PASS.

- [ ] **Step 6: Run the availability suite for regressions**

Run: `uv run pytest availability/ -q`
Expected: PASS. If a pre-existing test seeded personas or inactive analysts and expected them in the table, that test asserted the old (leaky) behavior — inspect it; if it's testing an unrelated concern, adjust its fixture to use active real analysts. Report any such change.

- [ ] **Step 7: Commit**

```bash
git add availability/services.py availability/
git commit -m "feat(availability): exclude retired/inactive analysts from availability eligibility (task #451)"
```

---

### Task 3: Meeting of Analysts — active-standing gate on role-derived membership

**Files:**
- Modify: `workgroups/models.py` — `Workgroup.is_member` (~line 380), `Workgroup.participants` auto-member query (~line 426-429); add two small helpers
- Modify: `workgroups/permissions.py:meeting_of_analysts_members()` (~line 119-124)
- Test: the workgroups/meeting test module (find it)

**Interfaces:**
- Consumes: `Profile.Standing.ACTIVE`.
- Produces: role-derived `auto_member_role` membership now requires active standing + active account + non-persona. New helpers `Workgroup._is_auto_member(user) -> bool` and `Workgroup._auto_member_user_qs()`.

- [ ] **Step 1: Locate the workgroups/meeting test module**

Run: `ls workgroups/ | grep -i test; grep -rln "meeting_of_analysts_members\|is_meeting_of_analysts\|auto_member_role" workgroups/*test*.py workgroups/tests/ 2>/dev/null`
Note where Meeting-of-Analysts / auto-member tests live and their fixture style (how they create a Workgroup with `auto_member_role`, or fetch the seeded Meeting-of-Analysts workgroup).

- [ ] **Step 2: Write the failing tests**

Add to the workgroups test module (adapt fixture style to the file; the pattern below constructs a role-derived workgroup directly so it doesn't depend on seeded data):

```python
import pytest

from accounts.models import Profile, User
from workgroups.models import Workgroup
from workgroups.permissions import meeting_of_analysts_members


def _analyst(email, standing=Profile.Standing.ACTIVE):
    u = User.objects.create_user(email=email)
    u.profile.role = Profile.Role.ANALYST
    u.profile.standing = standing
    u.profile.save()
    return u


@pytest.mark.django_db
def test_auto_member_workgroup_excludes_retired():
    wg = Workgroup.objects.create(
        name="Role Group", slug="role-group",
        kind=Workgroup.Kind.COMMITTEE, auto_member_role=Profile.Role.ANALYST,
    )
    active = _analyst("moa-active@example.com")
    retired = _analyst("moa-retired@example.com", standing=Profile.Standing.RETIRED)

    assert wg.is_member(active) is True
    assert wg.is_member(retired) is False
    pks = {p.user_id for p in wg.participants()}
    assert active.id in pks
    assert retired.id not in pks


@pytest.mark.django_db
def test_meeting_of_analysts_members_excludes_retired():
    active = _analyst("m-active@example.com")
    retired = _analyst("m-retired@example.com", standing=Profile.Standing.RETIRED)
    members = set(meeting_of_analysts_members().values_list("id", flat=True))
    assert active.id in members
    assert retired.id not in members
```

Note: if the test module has a helper that creates the seeded Meeting-of-Analysts workgroup, prefer reusing it; the direct-construct approach above is a fallback that exercises the same generic code path.

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest workgroups/ -k "excludes_retired" -q`
Expected: FAIL (retired analyst currently a member / participant / in the helper).

- [ ] **Step 4: Add the auto-member helpers to `Workgroup`**

In `workgroups/models.py`, add these methods to the `Workgroup` model (near `_user_role`, ~line 356):

```python
    def _is_auto_member(self, user) -> bool:
        """Whether ``user`` is a role-derived member of this group: an
        active-standing, active-account, non-persona holder of
        ``auto_member_role``. (Retired / on-leave / resigned / removed and
        deceased members are excluded — formation duties require active
        standing.)"""
        from accounts.models import Profile
        if not self.auto_member_role:
            return False
        p = getattr(user, "profile", None)
        return (
            p is not None
            and p.role == self.auto_member_role
            and p.standing == Profile.Standing.ACTIVE
            and not p.is_persona
            and getattr(user, "is_active", False)
        )

    def _auto_member_user_qs(self):
        """Users who are role-derived members of this group (see
        :meth:`_is_auto_member`) as a queryset, for roster enumeration."""
        from django.contrib.auth import get_user_model

        from accounts.models import Profile
        if not self.auto_member_role:
            return get_user_model().objects.none()
        return get_user_model().objects.filter(
            profile__role=self.auto_member_role,
            profile__standing=Profile.Standing.ACTIVE,
            profile__is_persona=False,
            is_active=True,
        )
```

- [ ] **Step 5: Use the predicate in `is_member`**

In `workgroups/models.py:Workgroup.is_member` (~line 380), replace:

```python
        if self.auto_member_role and self._user_role(user) == self.auto_member_role:
            return True
```

with:

```python
        if self._is_auto_member(user):
            return True
```

- [ ] **Step 6: Use the queryset in `participants`**

In `workgroups/models.py:Workgroup.participants` (~line 423-429), replace the inline query:

```python
        if self.auto_member_role:
            from django.contrib.auth import get_user_model

            users = (get_user_model().objects
                     .filter(profile__role=self.auto_member_role, is_active=True,
                             profile__is_persona=False)
                     .select_related("profile"))
            for u in users:
```

with:

```python
        if self.auto_member_role:
            users = self._auto_member_user_qs().select_related("profile")
            for u in users:
```

- [ ] **Step 7: Gate `meeting_of_analysts_members()`**

In `workgroups/permissions.py:meeting_of_analysts_members()` (~line 119-124), add the standing filter:

```python
    analyst_ids = list(
        User.objects.filter(
            profile__role=Profile.Role.ANALYST, is_active=True,
            profile__is_persona=False,
            profile__standing=Profile.Standing.ACTIVE,
        ).values_list("pk", flat=True)
    )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest workgroups/ -k "excludes_retired" -q`
Expected: PASS.

- [ ] **Step 9: Run the workgroups + admissions + formation suites for regressions**

Run: `uv run pytest workgroups/ admissions/ formation/ core/ -q`
Expected: PASS. The `is_member` auto-branch previously matched on role alone (so a persona/inactive analyst counted as a member); it now also requires active + non-persona + active-standing. If a test relied on the looser behavior, inspect it — it was asserting a leak. Report any adjustment.

- [ ] **Step 10: Commit**

```bash
git add workgroups/models.py workgroups/permissions.py workgroups/
git commit -m "feat(workgroups): retired/inactive analysts excluded from role-derived Meeting-of-Analysts membership (task #451)"
```

---

## Notes for the implementer

- **Why `is_active=True` matters alongside `standing == ACTIVE`:** deceased members keep their `standing` (e.g. `active`) but have `user.is_active=False`. Both conditions are needed so the gate excludes retired (via standing) *and* deceased (via is_active).
- **`appointable_people` picker** (`workgroups/views.py:558`) derives from `wg.participants()`, so gating `participants` automatically removes retired members from the Meeting officers picker — no separate change.
- **`groups_for`** (`workgroups/membership.py:185`) filters candidates through `wg.is_member` / `has_archive_access`, both of which now gate standing — no separate change.
- **No data migration:** membership is derived from standing, so setting a member to Retired via the Board tool drops them from these surfaces immediately. Existing stored availability rows for a now-retired analyst become inert via the `eligible_profiles()` gate.
