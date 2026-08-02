# Notification settings visibility — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/notifications/settings/` shows a member only the categories that can actually reach them.

**Architecture:** A new `notifications/audience.py` maps categories to per-user predicates and exposes `visible_categories(user)`. The settings view uses that one helper for both rendering and saving, so the rendered set and the saved set cannot drift. Delivery (`notify`, `resolve`, digests) is untouched.

**Tech Stack:** Django 5.2, pytest-django, uv.

Spec: `docs/superpowers/specs/2026-08-01-notification-settings-visibility-design.md`

## Global Constraints

- Work in the `plain-lantern` worktree (`/Users/picone/LSP-Web-Coordinator/lsp-website/.claude-worktrees/plain-lantern`), branched off `main`.
- `uv run pytest`, `uv run ruff check .` — both stay green.
- A category absent from `AUDIENCE` is visible to everyone. Never invert that default.
- Superusers see every category.
- Predicates import their gates **inside** the function (lazy) — `notifications` must not gain module-level dependencies on `committees`, `referrals`, `availability`, or `workgroups`.
- Verified gates, exactly as written: `committees.permissions.is_on_committee(user, "board")`; `core.access.has_staff_role`; `referrals.models.ReferralListMember` (`user` is a OneToOne with `related_name="referral_listing"`, and has an `is_active` flag that must be honoured); `workgroups.permissions.is_meeting_of_analysts(user)`; `availability.services.is_eligible(profile)`; `user.profile.owes_tuition` (a property).

---

### Task 1: The audience module

**Files:**
- Create: `notifications/audience.py`
- Test: Create `notifications/test_audience.py`

**Interfaces:**
- Produces: `AUDIENCE: dict[str, Callable]`, `applies(user, category) -> bool`, `visible_categories(user) -> list[str]` (in `CATEGORY_META` order).

- [ ] **Step 1: Write the failing tests**

Create `notifications/test_audience.py`:

```python
"""Which notification categories a member sees on the settings page."""

from __future__ import annotations

from datetime import date

import pytest

from accounts.models import User
from committees.models import Committee
from core.models import StaffRole
from notifications.audience import applies, visible_categories
from notifications.categories import CATEGORY_META, Category
from workgroups.models import WorkgroupMembership

pytestmark = pytest.mark.django_db


def _member(email="aud-member@x.test", role="candidate"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


def test_ungated_categories_are_visible_to_everyone():
    user = _member()
    assert applies(user, Category.PARLETRE_MENTION)
    assert applies(user, Category.ACCOUNT_SECURITY)


def test_plan_review_is_board_only():
    plain = _member("aud-plain@x.test", role="analyst")
    assert not applies(plain, Category.TUITION_PLAN_REVIEW)

    board = _member("aud-board@x.test", role="analyst")
    Committee.objects.get(slug="board").add_member(
        board, role=WorkgroupMembership.Role.MEMBER, start_date=date(2026, 1, 1),
    )
    assert applies(board, Category.TUITION_PLAN_REVIEW)


def test_suggestion_review_is_for_site_staff():
    plain = _member("aud-nosugg@x.test", role="analyst")
    assert not applies(plain, Category.SUGGESTION_FILED)

    staffer = _member("aud-sugg@x.test", role="analyst")
    StaffRole.objects.get(key=StaffRole.WEB_COORDINATOR).holders.add(staffer)
    assert applies(staffer, Category.SUGGESTION_FILED)


def test_referral_requests_reach_clinicians_and_the_coordinator():
    from referrals.models import ReferralListMember

    plain = _member("aud-noref@x.test", role="analyst")
    assert not applies(plain, Category.REFERRAL_REQUEST)

    clinician = _member("aud-clinician@x.test", role="analyst")
    ReferralListMember.objects.create(user=clinician)
    assert applies(clinician, Category.REFERRAL_REQUEST)

    coordinator = _member("aud-refcoord@x.test", role="analyst")
    StaffRole.objects.get(key=StaffRole.REFERRAL_COORDINATOR).holders.add(coordinator)
    assert applies(coordinator, Category.REFERRAL_REQUEST)


def test_an_inactive_referral_listing_does_not_count():
    from referrals.models import ReferralListMember

    former = _member("aud-former@x.test", role="analyst")
    ReferralListMember.objects.create(user=former, is_active=False)
    assert not applies(former, Category.REFERRAL_REQUEST)


def test_tuition_rows_follow_owes_tuition():
    student = _member("aud-student@x.test", role="candidate")
    assert student.profile.owes_tuition
    assert applies(student, Category.TUITION_REMINDER)
    assert applies(student, Category.TUITION_PLAN_DECISION)

    analyst = _member("aud-analyst@x.test", role="analyst")
    assert not analyst.profile.owes_tuition
    assert not applies(analyst, Category.TUITION_REMINDER)
    assert not applies(analyst, Category.TUITION_PLAN_DECISION)


def test_superusers_see_everything():
    su = User.objects.create_superuser(email="aud-su@x.test", password="x")
    assert set(visible_categories(su)) == set(CATEGORY_META)


def test_visible_categories_preserves_table_order():
    user = _member("aud-order@x.test", role="analyst")
    visible = visible_categories(user)
    assert visible == [c for c in CATEGORY_META if c in set(visible)]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest notifications/test_audience.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'notifications.audience'`.

- [ ] **Step 3: Write the module**

Create `notifications/audience.py`:

```python
"""Who sees a row for a category on the notification settings page.

Separate from :mod:`notifications.categories` on purpose. That module is the
delivery table — ``default_email_for`` there changes what dispatch *sends*.
This module changes only what the settings page *renders*: a hidden category
still notifies normally if it ever fires, which is what makes hiding safe.

A category absent from :data:`AUDIENCE` is visible to everyone — the safe
default, so adding a category never accidentally hides it. Predicates import
their gates lazily so ``notifications`` keeps no module-level dependency on
``committees`` / ``referrals`` / ``availability`` / ``workgroups``.
"""

from __future__ import annotations

from collections.abc import Callable

from .categories import CATEGORY_META, Category


def _is_board(user) -> bool:
    from committees.permissions import is_on_committee

    return is_on_committee(user, "board")


def _is_site_staff(user) -> bool:
    from core.access import has_staff_role
    from core.models import StaffRole

    return has_staff_role(user, StaffRole.WEB_COORDINATOR, StaffRole.WEB_DEVELOPER)


def _takes_referrals(user) -> bool:
    """On the referral list, or the coordinator who fields held submissions —
    both audiences share this category."""
    from core.access import has_staff_role
    from core.models import StaffRole
    from referrals.models import ReferralListMember

    if has_staff_role(user, StaffRole.REFERRAL_COORDINATOR):
        return True
    return ReferralListMember.objects.filter(user=user, is_active=True).exists()


def _is_meeting_of_analysts(user) -> bool:
    from workgroups.permissions import is_meeting_of_analysts

    return is_meeting_of_analysts(user)


def _has_availability_row(user) -> bool:
    from availability import services

    profile = getattr(user, "profile", None)
    return profile is not None and services.is_eligible(profile)


def _owes_tuition(user) -> bool:
    profile = getattr(user, "profile", None)
    return bool(profile and profile.owes_tuition)


#: category -> predicate. Absent means "everyone sees it".
AUDIENCE: dict[str, Callable[[object], bool]] = {
    Category.TUITION_PLAN_REVIEW: _is_board,
    Category.SUGGESTION_FILED: _is_site_staff,
    Category.REFERRAL_REQUEST: _takes_referrals,
    Category.EXTERNAL_CONTROL_ANALYST: _is_meeting_of_analysts,
    Category.AVAILABILITY_REVIEW: _has_availability_row,
    Category.TUITION_REMINDER: _owes_tuition,
    Category.TUITION_PLAN_DECISION: _owes_tuition,
}


def applies(user, category: str) -> bool:
    """Whether ``user`` should see a settings row for ``category``."""
    if getattr(user, "is_superuser", False):
        return True
    predicate = AUDIENCE.get(str(category))
    return True if predicate is None else bool(predicate(user))


def visible_categories(user) -> list[str]:
    """The categories to show ``user``, in ``CATEGORY_META`` order.

    The settings page renders from this **and** saves from it — a row that
    isn't rendered must not be written, or saving would silently switch it off.
    """
    return [c for c in CATEGORY_META if applies(user, c)]
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest notifications/test_audience.py -q`
Expected: PASS. If `test_referral_requests_reach_clinicians_and_the_coordinator` fails on a missing `StaffRole` row, check the role's seed key with `grep -rn "REFERRAL_COORDINATOR" core/migrations/` and use the seeded key.

- [ ] **Step 5: Commit**

```bash
git add notifications/audience.py notifications/test_audience.py
git commit -m "feat(notifications): per-member category audience for the settings page (task #491)"
```

---

### Task 2: Wire the settings page to it

**Files:**
- Modify: `notifications/views.py:88-147` (`settings_page`)
- Test: `notifications/test_audience.py`

**Interfaces:**
- Consumes: `visible_categories(user)` from Task 1.

- [ ] **Step 1: Write the failing tests**

Append to `notifications/test_audience.py`:

```python
def _settings_html(client, user):
    client.force_login(user)
    return client.get("/notifications/settings/").content.decode()


def test_settings_page_hides_the_board_row_from_a_plain_member(client):
    plain = _member("aud-page-plain@x.test", role="analyst")
    html = _settings_html(client, plain)
    assert "tuition_plan_review__email" not in html
    # A category everyone has is still there.
    assert "parletre_mention__email" in html


def test_settings_page_shows_the_board_row_to_a_board_member(client):
    board = _member("aud-page-board@x.test", role="analyst")
    Committee.objects.get(slug="board").add_member(
        board, role=WorkgroupMembership.Role.MEMBER, start_date=date(2026, 1, 1),
    )
    assert "tuition_plan_review__email" in _settings_html(client, board)


def test_saving_does_not_wipe_a_hidden_categorys_stored_preference(client):
    """The POST loop must skip what the page didn't render — otherwise a
    missing checkbox reads as 'off' and silently kills the bell."""
    from notifications.categories import EmailDelivery
    from notifications.models import NotificationPreference

    plain = _member("aud-page-keep@x.test", role="analyst")
    pref = NotificationPreference.objects.create(user=plain)
    pref.set(Category.TUITION_PLAN_REVIEW, in_app=True, email=EmailDelivery.IMMEDIATE)
    pref.save()

    client.force_login(plain)
    resp = client.post("/notifications/settings/", {
        "digest_cadence": "weekly",
        "parletre_mention__in_app": "on",
        "parletre_mention__email": "immediate",
    })
    assert resp.status_code == 302

    stored = NotificationPreference.objects.get(user=plain).overrides
    assert stored[Category.TUITION_PLAN_REVIEW] == {
        "in_app": True, "email": "immediate",
    }
    # What the member *could* see still saved.
    assert stored[Category.PARLETRE_MENTION]["email"] == "immediate"


def test_an_empty_section_disappears(client):
    """A member who is neither on the referral list nor the coordinator has no
    Referrals row, so the whole section is gone."""
    plain = _member("aud-page-noref@x.test", role="analyst")
    assert "Referrals" not in _settings_html(client, plain)
```

- [ ] **Step 2: Run and watch them fail**

Run: `uv run pytest notifications/test_audience.py -q`
Expected: FAIL — `test_settings_page_hides_the_board_row_from_a_plain_member` (row still rendered) and `test_saving_does_not_wipe_a_hidden_categorys_stored_preference` (override overwritten to off).

- [ ] **Step 3: Wire the view**

In `notifications/views.py`, import the helper:

```python
from .audience import visible_categories
```

In the POST branch, replace `for category in CATEGORY_META:` with:

```python
        # Only what the page rendered for this member — a category they can't
        # see submits no fields, and a missing checkbox would read as "off".
        for category in visible_categories(request.user):
```

In the GET branch, replace `for category, meta in CATEGORY_META.items():` with:

```python
    for category in visible_categories(request.user):
        meta = meta_for(category)
```

leaving the body of the loop unchanged.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest notifications/ -q`
Expected: PASS.

- [ ] **Step 5: Check for suite-wide fallout**

Run: `uv run pytest -q`
Expected: PASS. A test elsewhere that POSTs the settings form as a plain member and then asserts on a now-hidden category would need updating to a user who qualifies — fix by giving the test user the role, not by widening the audience.

- [ ] **Step 6: Commit**

```bash
git add notifications/views.py notifications/test_audience.py
git commit -m "feat(notifications): show only the categories that apply to the member (task #491)"
```

---

### Task 3: Verification

- [ ] **Step 1: No stray migrations**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected" — this change touches no models.

- [ ] **Step 2: Full suite + lint**

Run: `uv run pytest -q && uv run ruff check .`
Expected: both green.

- [ ] **Step 3: Confirm delivery is untouched**

Run: `uv run pytest payments/test_plan_notification_routing.py -q`
Expected: PASS — hiding a row must not change who gets notified.

- [ ] **Step 4: Report**

Summarize: which categories are now conditional, that stored preferences are preserved, and that a deploy needs a green CI run.
