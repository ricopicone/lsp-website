# New User Statuses Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three member states — Retired, Removed (new `Profile.Standing` values) and Deceased (an orthogonal `Profile.deceased_on` date) — with the right access, directory, billing, referral, and login consequences.

**Architecture:** Retired/Removed ride the existing `Profile.Standing` axis, so they inherit the `standing == ACTIVE` billing exemption for free. A new `NON_MEMBER_STANDINGS = {resigned, removed}` set makes the membership predicate and directory query standing-aware (this also newly hides `resigned`). Deceased is a separate `deceased_on` date that forces `User.is_active=False` (blocking password + magic-link login), keeps the member in the directory with an "In memoriam" marker, and — for Deceased only — auto-waives open charges. Removed uses a manual "Waive open charges" button (it's reinstatable). All financial and referral side-effects are orchestrated through one `accounts/lifecycle.py` module.

**Tech Stack:** Django 5.2, pytest-django, Tailwind v4 + DaisyUI (template markers). SQLite (dev) / Postgres (prod).

## Global Constraints

- Django custom user model `accounts.User` (email login, no username); every `User` auto-gets a `Profile` via post-save signal. Extend, never swap.
- `Profile.role` and `Profile.standing` are live caches kept in sync with `MembershipTenure` **only** through `accounts/membership.py:record_membership_change`. Route standing changes through it.
- **do-not-over-automate:** every automated financial path keeps a human override. Auto-waive applies to **Deceased only**; Removed gets a one-click button. Audit every waive with `Charge.add_note`.
- Member-facing site copy uses **commas, not em dashes** (`em-dash-prose-style` memory). In-repo markdown/docs use unspaced em dashes.
- Use DaisyUI semantic tokens (`text-base-content`, `text-primary`, …), never hardcoded colors. Tailwind scans templates only — any class must appear in a `.html`.
- Tests: pytest with `@pytest.mark.django_db`; create users via `User.objects.create_user(email=...)` (Profile auto-created). Keep the suite green (`uv run pytest`, `uv run ruff check .`).
- This session runs in the worktree `/Users/picone/LSP-Web-Coordinator/lsp-website/.claude-worktrees/silver-quartz`. **Edit files at this worktree path**, not the main repo path (`worktree-vs-main-path-trap` memory).

---

### Task 1: Model foundations — Standing values, `deceased_on`, predicates, `is_active` sync

**Files:**
- Modify: `accounts/models.py` (Standing enum ~92-99; add sets after `DIRECTORY_ROLES` ~442; add properties near `is_listed` ~472; extend `from_db` ~527-533 and `save` ~554-588; `MembershipTenure.standing` uses `Profile.Standing.choices` already, no edit needed)
- Create (migration): `accounts/migrations/00NN_new_user_statuses.py` (generated)
- Test: `accounts/tests.py`

**Interfaces:**
- Produces:
  - `Profile.Standing.RETIRED = "retired"`, `Profile.Standing.REMOVED = "removed"`
  - `Profile.deceased_on: date | None`
  - `Profile.NON_MEMBER_STANDINGS: frozenset[str]` = `{"resigned", "removed"}`
  - `Profile.REFERRAL_EXCLUDED_STANDINGS: frozenset[str]` = `{"retired", "resigned", "removed"}`
  - `Profile.is_deceased -> bool`
  - `Profile.is_active_member -> bool` (True iff `standing ∉ NON_MEMBER_STANDINGS` and not deceased and role in DIRECTORY_ROLES)
  - `Profile.save()` sets `self.user.is_active = (deceased_on is None)` when `deceased_on` changed.

- [ ] **Step 1: Write the failing tests**

Add to `accounts/tests.py`:

```python
from datetime import date


@pytest.mark.django_db
def test_new_standing_values_exist():
    assert Profile.Standing.RETIRED == "retired"
    assert Profile.Standing.REMOVED == "removed"
    # Emeritus is kept, not replaced.
    assert Profile.Standing.EMERITUS == "emeritus"


@pytest.mark.django_db
def test_non_member_standings_set():
    assert Profile.NON_MEMBER_STANDINGS == frozenset({"resigned", "removed"})


@pytest.mark.django_db
def test_setting_deceased_on_disables_login_on_save():
    user = User.objects.create_user(email="d@example.com")
    assert user.is_active is True
    user.profile.deceased_on = date(2026, 7, 22)
    user.profile.save()
    user.refresh_from_db()
    assert user.is_active is False
    assert user.profile.is_deceased is True


@pytest.mark.django_db
def test_clearing_deceased_on_reenables_login_on_save():
    user = User.objects.create_user(email="d2@example.com")
    user.profile.deceased_on = date(2026, 7, 22)
    user.profile.save()
    user.profile.deceased_on = None
    user.profile.save()
    user.refresh_from_db()
    assert user.is_active is True


@pytest.mark.django_db
def test_is_active_member_predicate():
    user = User.objects.create_user(email="m@example.com")
    p = user.profile
    p.role = Profile.Role.ANALYST
    p.standing = Profile.Standing.ACTIVE
    p.save()
    assert p.is_active_member is True
    p.standing = Profile.Standing.REMOVED
    p.save()
    assert p.is_active_member is False
    p.standing = Profile.Standing.RETIRED
    p.save()
    assert p.is_active_member is True  # retired is still a member
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest accounts/tests.py -k "standing or deceased or is_active_member" -q`
Expected: FAIL (`AttributeError: RETIRED` / `NON_MEMBER_STANDINGS` / `deceased_on`).

- [ ] **Step 3: Add the two Standing values**

In `accounts/models.py`, extend the `Standing` class (keep Emeritus):

```python
    class Standing(models.TextChoices):
        """Membership standing — orthogonal to role. Active is the default; the
        Board records transitions (on-leave, resigned, emeritus, retired,
        removed) via Membership administration. Deceased is a separate axis
        (``deceased_on``), not a standing."""
        ACTIVE = "active", _("Active")
        ON_LEAVE = "on_leave", _("On leave")
        RESIGNED = "resigned", _("Resigned")
        EMERITUS = "emeritus", _("Emeritus")
        RETIRED = "retired", _("Retired")
        REMOVED = "removed", _("Removed")
```

- [ ] **Step 4: Add the `deceased_on` field**

In `accounts/models.py`, add immediately after the `year_joined` field (~line 311):

```python
    deceased_on = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Date recorded as deceased. Orthogonal to standing — a member may "
            "be Retired and Deceased. Setting this disables the account "
            "(login off) for security; the member stays listed in the "
            "directory with an 'In memoriam' marker."
        ),
    )
```

- [ ] **Step 5: Add the standing sets and predicates**

In `accounts/models.py`, after the `DIRECTORY_ROLES` frozenset (~line 442) add:

```python
    #: Standings that are NOT members: no members-only access, off the public
    #: directory, not counted in member dashboards. Resigned joins Removed here.
    NON_MEMBER_STANDINGS = frozenset({"resigned", "removed"})

    #: Standings dropped from the Find-an-Analyst referral distribution pool
    #: (they are no longer taking new analysands). Deceased is excluded too, via
    #: ``is_deceased``. Emeritus / on-leave keep their referral listing.
    REFERRAL_EXCLUDED_STANDINGS = frozenset({"retired", "resigned", "removed"})
```

Then add these properties next to `is_listed` (~line 472):

```python
    @property
    def is_deceased(self) -> bool:
        return self.deceased_on is not None

    @property
    def is_active_member(self) -> bool:
        """Whether this profile currently counts as a member for access +
        dashboards: a directory role, an active-enough standing, and not
        deceased. (Directory *listing* keeps deceased — see the directory qs.)"""
        return (
            self.role in self.DIRECTORY_ROLES
            and self.standing not in self.NON_MEMBER_STANDINGS
            and not self.is_deceased
        )
```

- [ ] **Step 6: Snapshot `deceased_on` in `from_db` and sync `is_active` in `save`**

In `accounts/models.py`, extend the `from_db` loop (~line 530) to also snapshot `deceased_on`:

```python
    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        for f in ("location", "location_lat", "location_lng", "deceased_on"):
            if f in field_names:
                setattr(instance, "_loaded_" + f, values[field_names.index(f)])
        return instance
```

In `save`, just before `super().save(*args, **kwargs)` (~line 588), add the login sync:

```python
        # Deceased ⇒ account disabled (security); cleared ⇒ re-enabled. Synced
        # at the model level so every save path (admin, lifecycle helper,
        # scripts) is consistent. Heavier side-effects (waive, referral) live in
        # accounts.lifecycle, not here.
        deceased_being_saved = update_fields is None or "deceased_on" in update_fields
        if deceased_being_saved and self.user_id is not None:
            old_deceased = getattr(self, "_loaded_deceased_on", self._GEOCODE_UNSET)
            changed = old_deceased is self._GEOCODE_UNSET or old_deceased != self.deceased_on
            if changed:
                want_active = self.deceased_on is None
                if self.user.is_active != want_active:
                    self.user.is_active = want_active
                    self.user.save(update_fields=["is_active"])
```

At the end of `save` (near line 592 where the geocode snapshot is refreshed), also refresh the deceased snapshot:

```python
        self._loaded_deceased_on = self.deceased_on
```

- [ ] **Step 7: Generate and apply the migration**

Run: `uv run python manage.py makemigrations accounts && uv run python manage.py migrate`
Expected: one migration adding `deceased_on` and altering `standing` (+ `MembershipTenure.standing`) choices; migrate applies cleanly.

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest accounts/tests.py -k "standing or deceased or is_active_member" -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add accounts/models.py accounts/migrations/ accounts/tests.py
git commit -m "feat(accounts): add Retired/Removed standings + deceased_on with login sync (task #451)"
```

---

### Task 2: Membership predicate + directory become standing-aware

**Files:**
- Modify: `accounts/permissions.py:16-44` (`is_lsp_member`)
- Modify: `core/templatetags/core_tags.py` (duplicate `is_lsp_member`)
- Modify: `accounts/views.py:69-71` (`_directory_qs`) and `accounts/views.py:349-350` (`directory_map_data`)
- Modify: `accounts/models.py` (`is_listed` property ~469)
- Test: `accounts/tests.py`

**Interfaces:**
- Consumes: `Profile.NON_MEMBER_STANDINGS`, `Profile.is_deceased` (Task 1).
- Produces: `is_lsp_member` returns False for `standing ∈ NON_MEMBER_STANDINGS`; directory querysets exclude `NON_MEMBER_STANDINGS` but keep deceased.

- [ ] **Step 1: Write the failing tests**

Add to `accounts/tests.py`:

```python
@pytest.mark.django_db
def test_removed_member_is_not_lsp_member():
    from accounts.permissions import is_lsp_member
    user = User.objects.create_user(email="rm@example.com")
    user.profile.role = Profile.Role.CANDIDATE
    user.profile.standing = Profile.Standing.REMOVED
    user.profile.save()
    assert is_lsp_member(user) is False


@pytest.mark.django_db
def test_resigned_member_is_not_lsp_member():
    from accounts.permissions import is_lsp_member
    user = User.objects.create_user(email="rs@example.com")
    user.profile.role = Profile.Role.ANALYST
    user.profile.standing = Profile.Standing.RESIGNED
    user.profile.save()
    assert is_lsp_member(user) is False


@pytest.mark.django_db
def test_retired_member_stays_lsp_member():
    from accounts.permissions import is_lsp_member
    user = User.objects.create_user(email="rt@example.com")
    user.profile.role = Profile.Role.ANALYST
    user.profile.standing = Profile.Standing.RETIRED
    user.profile.save()
    assert is_lsp_member(user) is True


@pytest.mark.django_db
def test_directory_excludes_removed_and_resigned_keeps_deceased(client):
    from datetime import date
    for email, standing, deceased in [
        ("active@x.test", Profile.Standing.ACTIVE, None),
        ("removed@x.test", Profile.Standing.REMOVED, None),
        ("resigned@x.test", Profile.Standing.RESIGNED, None),
        ("deceased@x.test", Profile.Standing.ACTIVE, date(2026, 7, 22)),
    ]:
        u = User.objects.create_user(email=email, first_name="T", last_name=email[:4])
        u.profile.role = Profile.Role.ANALYST
        u.profile.standing = standing
        u.profile.public = True
        u.profile.deceased_on = deceased
        u.profile.save()

    from accounts.views import _directory_qs
    listed = {p.user.email for p in _directory_qs()}
    assert "active@x.test" in listed
    assert "deceased@x.test" in listed       # deceased stays listed
    assert "removed@x.test" not in listed
    assert "resigned@x.test" not in listed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest accounts/tests.py -k "lsp_member or directory_excludes" -q`
Expected: FAIL (removed/resigned still counted as members / listed).

- [ ] **Step 3: Make `is_lsp_member` standing-aware**

In `accounts/permissions.py`, replace the directory-role check (lines 33-35) with:

```python
    profile = getattr(user, "profile", None)
    if (
        profile is not None
        and profile.role in Profile.DIRECTORY_ROLES
        and profile.standing not in Profile.NON_MEMBER_STANDINGS
    ):
        return True
```

- [ ] **Step 4: Mirror the change in the template tag**

In `core/templatetags/core_tags.py`, find the duplicate `is_lsp_member` (~line 20) and apply the same `standing not in Profile.NON_MEMBER_STANDINGS` guard to its directory-role branch. (If it delegates to `accounts.permissions.is_lsp_member`, no change is needed — verify by reading the function; keep the two in sync.)

- [ ] **Step 5: Make the directory querysets standing-aware**

In `accounts/views.py`, `_directory_qs` (line 70-71), change the filter to exclude non-member standings while keeping deceased:

```python
        Profile.objects
        .filter(role__in=Profile.DIRECTORY_ROLES, public=True)
        .exclude(standing__in=Profile.NON_MEMBER_STANDINGS)
```

In `directory_map_data` (~line 349-350), apply the same `.exclude(standing__in=Profile.NON_MEMBER_STANDINGS)` to its `Profile.objects.filter(role__in=Profile.DIRECTORY_ROLES, public=True)` query.

- [ ] **Step 6: Make `is_listed` consistent**

In `accounts/models.py`, update `is_listed` (~469) so nav/link helpers agree with the directory query:

```python
    @property
    def is_listed(self) -> bool:
        """Shown publicly: role-eligible, opted in, and not a non-member
        standing. Deceased members stay listed (with a memorial marker)."""
        return (
            self.is_in_directory
            and self.public
            and self.standing not in self.NON_MEMBER_STANDINGS
        )
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest accounts/tests.py -k "lsp_member or directory_excludes" -q`
Expected: PASS.

- [ ] **Step 8: Run the broader accounts + directory suite for regressions**

Run: `uv run pytest accounts/ -q`
Expected: PASS (no existing directory test broke).

- [ ] **Step 9: Commit**

```bash
git add accounts/permissions.py core/templatetags/core_tags.py accounts/views.py accounts/models.py accounts/tests.py
git commit -m "feat(accounts): hide removed/resigned from directory + member access; keep deceased listed (task #451)"
```

---

### Task 3: Directory memorial marker + suppress referral/contact CTA for deceased

**Files:**
- Modify: the directory card + detail templates (find with the grep in Step 1)
- Test: `accounts/tests.py`

**Interfaces:**
- Consumes: `Profile.is_deceased` (Task 1).
- Produces: an "In memoriam" marker rendered for deceased members; no referral/contact call-to-action on their card/detail.

- [ ] **Step 1: Locate the directory templates and the referral/contact CTA**

Run:
```bash
grep -rln "directory" accounts/templates/ | head
grep -rn "request a referral\|Find an Analyst\|mailto\|display_email\|referral" accounts/templates/accounts/directory*.html
```
Expected: the card template (grid item) and detail template. Note the file paths and the block that renders contact/referral actions.

- [ ] **Step 2: Write the failing test**

Add to `accounts/tests.py`:

```python
@pytest.mark.django_db
def test_directory_shows_memorial_marker_for_deceased(client):
    from datetime import date
    u = User.objects.create_user(email="memoriam@x.test", first_name="Jane", last_name="Doe")
    u.profile.role = Profile.Role.ANALYST
    u.profile.public = True
    u.profile.deceased_on = date(2026, 7, 22)
    u.profile.save()

    resp = client.get(f"/directory/{u.profile.directory_slug}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "In memoriam" in body


@pytest.mark.django_db
def test_directory_detail_hides_referral_cta_for_deceased(client):
    from datetime import date
    u = User.objects.create_user(email="nocta@x.test", first_name="John", last_name="Roe")
    u.profile.role = Profile.Role.ANALYST
    u.profile.public = True
    u.profile.public_email = "john@x.test"
    u.profile.deceased_on = date(2026, 7, 22)
    u.profile.save()

    resp = client.get(f"/directory/{u.profile.directory_slug}/")
    body = resp.content.decode()
    # No contact email link for a deceased member.
    assert "mailto:john@x.test" not in body
```

Note: if the directory detail URL differs, adjust to the reversed URL name found in Step 1 (e.g. `reverse("directory_detail", args=[slug])`).

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest accounts/tests.py -k "memorial or referral_cta" -q`
Expected: FAIL (no marker; mailto present).

- [ ] **Step 4: Add the memorial marker**

In the directory **detail** template, near the member's name/role heading, add (member-facing copy uses commas, DaisyUI tokens):

```html
{% if profile.is_deceased %}
  <p class="text-sm text-base-content/60 italic mt-1">In memoriam</p>
{% endif %}
```

In the directory **card** template, add a compact variant under the name:

```html
{% if profile.is_deceased %}
  <span class="text-xs text-base-content/60 italic">In memoriam</span>
{% endif %}
```

- [ ] **Step 5: Suppress the contact/referral CTA for deceased**

Wrap the contact-email / referral action block found in Step 1 so it is skipped for deceased members. For example, if the detail template renders a contact link:

```html
{% if not profile.is_deceased %}
  {# ... existing contact email / request-a-referral block ... #}
{% endif %}
```

Apply the same guard to any "Find an Analyst" / referral CTA on the card.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest accounts/tests.py -k "memorial or referral_cta" -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add accounts/templates/ accounts/tests.py
git commit -m "feat(accounts): 'In memoriam' marker + no contact CTA for deceased members in directory (task #451)"
```

---

### Task 4: `waive_open_charges` helper (payments)

**Files:**
- Modify: `payments/charges.py` (add function near `void_registration_charge` ~270)
- Test: `payments/test_charges_sync.py`

**Interfaces:**
- Produces: `payments.charges.waive_open_charges(user, *, reason: str, by=None) -> int` — sets every OPEN charge on the user to WAIVED with an audited note; idempotent; returns count waived.

- [ ] **Step 1: Write the failing test**

Add to `payments/test_charges_sync.py` (mirror its existing imports/fixtures):

```python
from datetime import date
from decimal import Decimal

import pytest

from accounts.models import User
from payments.charges import waive_open_charges
from payments.models import Charge


@pytest.mark.django_db
def test_waive_open_charges_waives_open_only():
    u = User.objects.create_user(email="w@example.com")
    open_c = Charge.objects.create(
        user=u, category=Charge.Category.DUES, amount=Decimal("100"),
        effective_date=date(2025, 9, 1), status=Charge.Status.OPEN,
    )
    already = Charge.objects.create(
        user=u, category=Charge.Category.TUITION, amount=Decimal("200"),
        effective_date=date(2024, 9, 1), status=Charge.Status.WAIVED,
    )

    n = waive_open_charges(u, reason="Member deceased")
    assert n == 1
    open_c.refresh_from_db()
    already.refresh_from_db()
    assert open_c.status == Charge.Status.WAIVED
    assert "Member deceased" in open_c.notes
    assert already.status == Charge.Status.WAIVED  # untouched

    # Idempotent: a second call waives nothing.
    assert waive_open_charges(u, reason="again") == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest payments/test_charges_sync.py -k waive_open_charges -q`
Expected: FAIL (`ImportError: cannot import name 'waive_open_charges'`).

- [ ] **Step 3: Implement the helper**

In `payments/charges.py`, add after `void_registration_charge` (~line 283):

```python
def waive_open_charges(user, *, reason: str, by=None) -> int:
    """Waive every OPEN charge on ``user``'s account (dues / tuition /
    registration), writing an audited note on each. Idempotent — WAIVED/VOID
    rows are left untouched. Returns the number of charges waived.

    Used when a member is marked Deceased (auto) or Removed (via the treasurer
    one-click action). Waiving is audit-only; it never moves money.
    """
    note = f"{reason} (waived by {by.email})" if by is not None else reason
    n = 0
    for c in Charge.objects.filter(user=user, status=Charge.Status.OPEN):
        c.status = Charge.Status.WAIVED
        c.add_note(note, save=False)
        c.save(update_fields=("status", "notes"))
        n += 1
    return n
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest payments/test_charges_sync.py -k waive_open_charges -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add payments/charges.py payments/test_charges_sync.py
git commit -m "feat(payments): waive_open_charges helper for deceased/removed members (task #451)"
```

---

### Task 5: Lifecycle orchestration — `accounts/lifecycle.py`

**Files:**
- Create: `accounts/lifecycle.py`
- Modify: `accounts/membership.py:record_membership_change` (call `sync_referral_listing` after the live-cache write ~113)
- Test: `accounts/test_lifecycle.py` (new)

**Interfaces:**
- Consumes: `Profile` (Task 1), `payments.charges.waive_open_charges` (Task 4), `referrals.models.ReferralListMember`.
- Produces:
  - `accounts.lifecycle.set_deceased(member, deceased_on, *, by=None) -> None`
  - `accounts.lifecycle.clear_deceased(member, *, by=None) -> None`
  - `accounts.lifecycle.sync_referral_listing(member) -> None` (deactivate the member's `ReferralListMember` when non-practicing)

- [ ] **Step 1: Write the failing tests**

Create `accounts/test_lifecycle.py`:

```python
from datetime import date
from decimal import Decimal

import pytest

from accounts.lifecycle import clear_deceased, set_deceased, sync_referral_listing
from accounts.models import Profile, User
from payments.models import Charge
from referrals.models import ReferralListMember


@pytest.mark.django_db
def test_set_deceased_disables_login_and_waives_and_delists_referrals():
    u = User.objects.create_user(email="dec@example.com")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    Charge.objects.create(
        user=u, category=Charge.Category.DUES, amount=Decimal("150"),
        effective_date=date(2025, 9, 1), status=Charge.Status.OPEN,
    )
    rlm = ReferralListMember.objects.create(user=u, is_active=True)

    set_deceased(u, date(2026, 7, 22))

    u.refresh_from_db()
    assert u.is_active is False
    assert u.profile.deceased_on == date(2026, 7, 22)
    assert not Charge.objects.filter(user=u, status=Charge.Status.OPEN).exists()
    rlm.refresh_from_db()
    assert rlm.is_active is False


@pytest.mark.django_db
def test_removed_standing_delists_referrals_but_does_not_waive():
    from accounts.membership import record_membership_change
    u = User.objects.create_user(email="rmv@example.com")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.save()
    Charge.objects.create(
        user=u, category=Charge.Category.DUES, amount=Decimal("100"),
        effective_date=date(2025, 9, 1), status=Charge.Status.OPEN,
    )
    rlm = ReferralListMember.objects.create(user=u, is_active=True)

    record_membership_change(
        u, role=Profile.Role.CANDIDATE, standing=Profile.Standing.REMOVED,
        effective_ay=2026,
    )

    rlm.refresh_from_db()
    assert rlm.is_active is False                       # delisted
    assert Charge.objects.filter(                       # NOT auto-waived
        user=u, status=Charge.Status.OPEN).exists()


@pytest.mark.django_db
def test_clear_deceased_reenables_login():
    u = User.objects.create_user(email="rev@example.com")
    set_deceased(u, date(2026, 7, 22))
    clear_deceased(u)
    u.refresh_from_db()
    assert u.is_active is True
    assert u.profile.deceased_on is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest accounts/test_lifecycle.py -q`
Expected: FAIL (`ModuleNotFoundError: accounts.lifecycle`).

- [ ] **Step 3: Implement `accounts/lifecycle.py`**

```python
"""Member lifecycle side-effects for terminal/non-member states (task #451).

Standing changes (retired/resigned/removed) and the orthogonal ``deceased_on``
date carry consequences beyond the Profile row: login on/off, waiving open
charges, and dropping the member from the referral pool. This module is the one
place those side-effects are orchestrated, so every entry point (Board admin,
Django admin action, scripts) behaves the same.

Imports of ``payments`` and ``referrals`` stay lazy to avoid import cycles
(accounts is a foundation app).
"""

from __future__ import annotations

from django.db import transaction

from .models import Profile


def sync_referral_listing(member) -> None:
    """Deactivate the member's referral listing when they are no longer taking
    new analysands (retired / resigned / removed / deceased). Reinstatement does
    NOT auto-reactivate it — the member re-opts via the profile editor."""
    from referrals.models import ReferralListMember

    profile = getattr(member, "profile", None)
    if profile is None:
        return
    excluded = (
        profile.standing in Profile.REFERRAL_EXCLUDED_STANDINGS
        or profile.is_deceased
    )
    if excluded:
        ReferralListMember.objects.filter(user=member, is_active=True).update(
            is_active=False,
        )


@transaction.atomic
def set_deceased(member, deceased_on, *, by=None) -> None:
    """Mark ``member`` deceased: record the date (disables login via
    Profile.save), auto-waive all open charges, and drop them from referrals."""
    from payments.charges import waive_open_charges

    profile = member.profile
    profile.deceased_on = deceased_on
    profile.save(update_fields=["deceased_on"])  # syncs user.is_active = False
    waive_open_charges(member, reason="Waived — member deceased", by=by)
    sync_referral_listing(member)


@transaction.atomic
def clear_deceased(member, *, by=None) -> None:
    """Reverse a deceased mark: clear the date and re-enable login. Does NOT
    un-waive charges or re-list referrals (those were deliberate actions)."""
    profile = member.profile
    profile.deceased_on = None
    profile.save(update_fields=["deceased_on"])  # syncs user.is_active = True
```

- [ ] **Step 4: Hook `record_membership_change` to sync referrals**

In `accounts/membership.py`, at the end of `record_membership_change` (after `profile.save(update_fields=["role", "standing"])`, before `return tenure`, ~line 113):

```python
    # Non-member / non-practicing standings drop the member from the referral
    # pool (kept lazy — referrals imports accounts).
    from accounts.lifecycle import sync_referral_listing
    sync_referral_listing(member)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest accounts/test_lifecycle.py -q`
Expected: PASS.

- [ ] **Step 6: Run the membership + referrals suites for regressions**

Run: `uv run pytest accounts/ referrals/ -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add accounts/lifecycle.py accounts/membership.py accounts/test_lifecycle.py
git commit -m "feat(accounts): lifecycle orchestration for deceased + non-member standings (task #451)"
```

---

### Task 6: Board admin UI — deceased control + Removed "Waive open charges" button; Django admin field

**Files:**
- Modify: `core/staff.py:board_membership_admin` (~314-363) — handle `action=set_deceased` / `action=clear_deceased` / `action=waive_charges` POSTs
- Modify: the board membership admin template (find with grep in Step 1)
- Modify: `accounts/admin.py` (expose `deceased_on` on the Profile admin)
- Test: `core/tests` (the file covering `board_membership_admin`) and `accounts/tests.py`

**Interfaces:**
- Consumes: `accounts.lifecycle.set_deceased/clear_deceased` (Task 5), `payments.charges.waive_open_charges` (Task 4), `payments.ledger` account balance (for the Removed open-balance display).
- Produces: POST actions on `board_membership_admin`; a `deceased_on` widget in Django admin.

- [ ] **Step 1: Locate the board membership template and the balance helper**

Run:
```bash
grep -rln "board_membership_admin\|Membership administration" core/templates/ | head
grep -n "def member_account\|def account_balance\|open_balance\|balance" payments/ledger.py | head
```
Note the template path and the ledger function that returns a member's open balance (e.g. `member_account(user)` with a `balance`/`open_total`).

- [ ] **Step 2: Write the failing tests**

Add to the test module that covers `board_membership_admin` (create the client as an authorized Board user the way neighboring tests do; if there's a `board_user`/`staff_client` fixture, reuse it). Example using a superuser client:

```python
from datetime import date

import pytest

from accounts.models import Profile, User


@pytest.mark.django_db
def test_board_admin_set_deceased_disables_login(client):
    admin = User.objects.create_superuser(email="boss@example.com", password="pw")
    client.force_login(admin)
    member = User.objects.create_user(email="member@example.com")
    member.profile.role = Profile.Role.ANALYST
    member.profile.save()

    resp = client.post("/admin-tools/board/membership/", {
        "action": "set_deceased",
        "member": member.pk,
        "deceased_on": "2026-07-22",
    })
    assert resp.status_code in (200, 302)
    member.refresh_from_db()
    assert member.is_active is False
    assert member.profile.deceased_on == date(2026, 7, 22)


@pytest.mark.django_db
def test_board_admin_waive_charges_button(client):
    from decimal import Decimal
    from payments.models import Charge
    admin = User.objects.create_superuser(email="boss2@example.com", password="pw")
    client.force_login(admin)
    member = User.objects.create_user(email="rmv2@example.com")
    member.profile.role = Profile.Role.CANDIDATE
    member.profile.standing = Profile.Standing.REMOVED
    member.profile.save()
    Charge.objects.create(
        user=member, category=Charge.Category.DUES, amount=Decimal("100"),
        effective_date=date(2025, 9, 1), status=Charge.Status.OPEN,
    )

    resp = client.post("/admin-tools/board/membership/", {
        "action": "waive_charges",
        "member": member.pk,
    })
    assert resp.status_code in (200, 302)
    assert not Charge.objects.filter(
        user=member, status=Charge.Status.OPEN).exists()
```

Note: the `board_membership_admin` URL is `/admin-tools/board/membership/` (name `board_membership_admin`).

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest -k "board_admin_set_deceased or board_admin_waive" -q`
Expected: FAIL (actions not handled; charges remain / login stays on).

- [ ] **Step 4: Handle the new POST actions in the view**

In `core/staff.py:board_membership_admin`, at the top of the `if request.method == "POST":` block (~line 332), branch on an `action` field before the existing membership-change handling:

```python
    if request.method == "POST":
        action = request.POST.get("action")
        if action in {"set_deceased", "clear_deceased", "waive_charges"}:
            from django.contrib import messages

            from accounts.lifecycle import clear_deceased, set_deceased
            from payments.charges import waive_open_charges

            member = get_object_or_404(User, pk=request.POST.get("member"))
            if action == "set_deceased":
                from datetime import date as _date
                raw = request.POST.get("deceased_on") or ""
                try:
                    d = _date.fromisoformat(raw)
                except ValueError:
                    messages.error(request, "Enter a valid date (YYYY-MM-DD).")
                else:
                    set_deceased(member, d, by=request.user)
                    messages.success(
                        request,
                        f"Recorded {member.get_full_name() or member.email} "
                        "as deceased. The account is disabled and open charges "
                        "were waived.",
                    )
            elif action == "clear_deceased":
                clear_deceased(member, by=request.user)
                messages.success(request, "Cleared the deceased mark; the account is re-enabled.")
            elif action == "waive_charges":
                n = waive_open_charges(
                    member, reason="Waived — member removed", by=request.user,
                )
                messages.success(request, f"Waived {n} open charge(s).")
            return redirect(f"{reverse('board_membership_admin')}?member={member.pk}")
```

Leave the existing membership-change `form` handling to run when `action` is absent.

- [ ] **Step 5: Pass the member's open balance + deceased state to the template**

`payments.ledger.member_account(user)` returns a dict whose `"owes"` key is the
amount currently owed (a `Decimal`, `0` when square or in credit). In the GET
branch of the view where `member` context is assembled, add:

```python
    open_owes = None
    if member is not None:
        from payments.ledger import member_account
        open_owes = member_account(member)["owes"]  # Decimal; 0 if nothing owed
```

Add `open_owes` to the template context dict.

- [ ] **Step 6: Render the controls in the template**

In the board membership admin template (from Step 1), inside the block shown when a `member` is selected, add (member-facing copy uses commas; DaisyUI tokens):

```html
<div class="mt-6 border-t border-base-300 pt-4 space-y-4">
  {% if member.profile.is_deceased %}
    <form method="post" class="flex items-center gap-3">
      {% csrf_token %}
      <input type="hidden" name="action" value="clear_deceased">
      <input type="hidden" name="member" value="{{ member.pk }}">
      <span class="text-sm text-base-content/70">
        Recorded deceased on {{ member.profile.deceased_on }}. Account disabled.
      </span>
      <button class="btn btn-sm btn-outline">Clear deceased mark</button>
    </form>
  {% else %}
    <form method="post" class="flex flex-wrap items-end gap-3">
      {% csrf_token %}
      <input type="hidden" name="action" value="set_deceased">
      <input type="hidden" name="member" value="{{ member.pk }}">
      <label class="text-sm">
        Mark deceased (date)
        <input type="date" name="deceased_on" required
               class="input input-bordered input-sm ml-2">
      </label>
      <button class="btn btn-sm btn-warning btn-outline">Mark deceased</button>
    </form>
    <p class="text-xs text-base-content/60">
      Disables the account for security, waives open charges, and removes the
      member from referrals. The member stays listed with an In memoriam marker.
    </p>
  {% endif %}

  {% if member.profile.standing == "removed" and open_owes %}
    <form method="post" class="flex items-center gap-3">
      {% csrf_token %}
      <input type="hidden" name="action" value="waive_charges">
      <input type="hidden" name="member" value="{{ member.pk }}">
      <span class="text-sm text-warning">Open balance: ${{ open_owes }}</span>
      <button class="btn btn-sm btn-outline">Waive open charges</button>
    </form>
  {% endif %}
</div>
```

- [ ] **Step 7: Expose `deceased_on` on the Django admin Profile**

In `accounts/admin.py`, add `deceased_on` to the Profile admin's `fields`/`fieldsets` (find the `ProfileAdmin` or inline). Direct edits there still sync `is_active` via `Profile.save()` (Task 1); the full workflow — waive + referral delisting — is the Board admin path. Add a short `help_text`-style comment in the admin if there's a description block.

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest -k "board_admin_set_deceased or board_admin_waive" -q`
Expected: PASS.

- [ ] **Step 9: Run the core/staff suite for regressions**

Run: `uv run pytest core/ -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add core/staff.py core/templates/ accounts/admin.py
git add -A  # picks up the test file(s) touched
git commit -m "feat(admin): Board membership deceased control + Removed waive-charges button (task #451)"
```

---

### Task 7: Dashboards + safety belts

**Files:**
- Modify: `core/staff.py:board_governance` (~505-518, member_qs) and the board-appointments appointable list (~447-451)
- Modify: `payments/charges.py:sync_tuition_charges` (standing hard-stop, ~103-105)
- Modify: `payments/management/commands/send_registration_reminders.py` (~70-76, student reminder queryset)
- Test: `core/tests`, `payments/test_charges_sync.py`, `payments/test_*` for the reminder command

**Interfaces:**
- Consumes: `Profile.NON_MEMBER_STANDINGS`, `Profile.deceased_on` (Task 1).
- Produces: `board_governance` counts exclude non-member standings + deceased; `sync_tuition_charges` no-ops for non-member/deceased; `send_registration_reminders` skips removed/resigned/deceased students.

- [ ] **Step 1: Write the failing tests**

Add to `payments/test_charges_sync.py`:

```python
@pytest.mark.django_db
def test_sync_tuition_charges_noops_for_removed_member():
    from payments.charges import sync_tuition_charges
    from payments.models import Charge
    u = User.objects.create_user(email="trm@example.com")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.standing = Profile.Standing.REMOVED
    u.profile.save()
    sync_tuition_charges(u)
    assert not Charge.objects.filter(
        user=u, category=Charge.Category.TUITION).exists()
```

Add to the `core` test module covering `board_governance` (reuse its Board fixture/client):

```python
@pytest.mark.django_db
def test_board_governance_excludes_removed_members(client):
    from accounts.models import Profile, User
    admin = User.objects.create_superuser(email="gov@example.com", password="pw")
    client.force_login(admin)
    active = User.objects.create_user(email="ga@example.com")
    active.profile.role = Profile.Role.ANALYST
    active.profile.save()
    removed = User.objects.create_user(email="gr@example.com")
    removed.profile.role = Profile.Role.ANALYST
    removed.profile.standing = Profile.Standing.REMOVED
    removed.profile.save()

    resp = client.get("/admin-tools/board/governance/")  # name: board_governance
    assert resp.status_code == 200
    # total_members counts active but not removed
    assert resp.context["total_members"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest payments/test_charges_sync.py -k tuition_noops core/ -k board_governance_excludes -q`
Expected: FAIL (tuition charge minted; removed counted).

- [ ] **Step 3: Add the tuition minting hard-stop**

In `payments/charges.py:sync_tuition_charges`, right after the existing role guard (~line 105, after `if profile is None or profile.role not in Profile.IN_TRAINING_ROLES: return`):

```python
    if profile.standing in Profile.NON_MEMBER_STANDINGS or profile.deceased_on:
        return  # removed / resigned / deceased — never mint new tuition
```

- [ ] **Step 4: Exclude non-member standings + deceased from board_governance**

In `core/staff.py:board_governance`, extend `member_qs` (~505):

```python
    member_qs = Profile.objects.filter(
        role__in=Profile.DIRECTORY_ROLES, is_persona=False, user__is_active=True,
    ).exclude(standing__in=Profile.NON_MEMBER_STANDINGS)
```

(`user__is_active=True` already drops deceased, since `deceased_on` set → `is_active=False`.) Apply the same `.exclude(standing__in=Profile.NON_MEMBER_STANDINGS)` to the board-appointments appointable list (~447-451) so removed members aren't appointable.

- [ ] **Step 5: Filter the registration reminder queryset**

In `payments/management/commands/send_registration_reminders.py`, extend the `awaiting` queryset (~70-76):

```python
        from accounts.models import Profile
        awaiting = (
            Registration.objects.filter(
                status=Registration.Status.AWAITING_PAYMENT,
                decided_at__isnull=False,
                quoted_amount__gt=0,
            )
            .filter(user__is_active=True)
            .exclude(user__profile__standing__in=Profile.NON_MEMBER_STANDINGS)
            .filter(due).select_related("event", "user")
        )
```

(`user__is_active=True` covers deceased; the exclude covers removed/resigned.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest payments/test_charges_sync.py -k tuition_noops core/ -k board_governance_excludes -q`
Expected: PASS.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q && uv run ruff check .`
Expected: PASS + clean lint.

- [ ] **Step 8: Commit**

```bash
git add core/staff.py payments/charges.py payments/management/commands/send_registration_reminders.py payments/test_charges_sync.py core/
git commit -m "feat(payments,core): exclude removed/deceased from dashboards, tuition minting, registration nags (task #451)"
```

---

## Notes for the implementer

- **Reinstatement semantics:** setting a Removed member back to `active` (via the Board membership form) restores member access and directory listing automatically. It does **not** un-waive charges or re-list referrals — those were deliberate actions. This is intended (design §5, decision (a)).
- **Deceased + Retired coexist:** `deceased_on` is orthogonal. A retired analyst who dies keeps `standing=retired` and gains a `deceased_on` date. Both predicates apply.
- **Two waive triggers, one helper:** Deceased auto-waives inside `set_deceased`; Removed waives via the Board button. Both call `waive_open_charges` — keep it the single source.
- **Confirmed URLs** (already baked into the tests): board membership `/admin-tools/board/membership/` (`board_membership_admin`), board governance `/admin-tools/board/governance/` (`board_governance`), directory detail `/directory/<slug>/` (`directory_detail`). The board-membership template path is discovered in Task 6 Step 1 — confirm it before editing.
```
