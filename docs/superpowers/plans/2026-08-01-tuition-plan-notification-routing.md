# Tuition payment-plan notification routing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A tuition payment-plan application emails the Treasurer, not every Board member, while the Board keeps the bell row, the queue, and the decision.

**Architecture:** `CategoryMeta` gains an optional `default_email_for(user)` callable that `notifications.preferences.resolve()` consults when the member has no explicit override. `TUITION_PLAN_REVIEW` uses it to default to immediate email for the Treasurer and off for everyone else. The applicant's decision notice moves to its own category so quieting reviewers doesn't silence applicants. A data migration drops the incidental overrides the settings page writes for every category on save, and a `documents` data migration rewrites the Tuition Assistance page.

**Tech Stack:** Django 5.2, pytest-django, uv.

Spec: `docs/superpowers/specs/2026-08-01-tuition-plan-notification-routing-design.md`

## Global Constraints

- Work in the `keen-ledger` worktree (`/Users/picone/LSP-Web-Coordinator/lsp-website/.claude-worktrees/keen-ledger`), branched off `main`. The `brisk-raven` worktree is stale — never edit there.
- Run tests with `uv run pytest`, lint with `uv run ruff check .`. Both must stay green.
- Member-facing site copy uses commas, not em dashes (house style).
- `core.access.has_staff_role` is explicit-holders-only; it does **not** implicitly include superusers. That is the intended semantics here.
- Never create `Notification` rows directly — everything goes through `notifications.dispatch.notify`.
- Emails dispatch on `transaction.on_commit`, so any test asserting on `mailoutbox` must wrap the call in `django_capture_on_commit_callbacks(execute=True)`.

---

### Task 1: Role-sensitive category default

**Files:**
- Modify: `notifications/categories.py` (the `CategoryMeta` dataclass, ~line 115)
- Modify: `notifications/preferences.py:26-39`
- Test: `notifications/tests.py`

**Interfaces:**
- Produces: `CategoryMeta.default_email_for: Callable[[user], str] | None = None` — returns an `EmailDelivery` value for one recipient. `resolve(user, category)` uses it in place of `meta.default_email` when the member has no stored override for that category.

- [ ] **Step 1: Write the failing tests**

Append to `notifications/tests.py`:

```python
@pytest.mark.django_db
def test_default_email_for_gives_each_recipient_its_own_default(monkeypatch):
    from notifications import categories as cats

    meta = cats.CategoryMeta(
        cats.SECTION_ACCOUNT, "Test queue",
        default_email_for=lambda u: (
            EmailDelivery.IMMEDIATE if u.email == "owner@x.co" else EmailDelivery.OFF
        ),
    )
    monkeypatch.setitem(cats.CATEGORY_META, "test_queue", meta)

    owner = make_user("owner@x.co")
    bystander = make_user("bystander@x.co")

    assert resolve(owner, "test_queue").email is True
    assert resolve(bystander, "test_queue").email is False
    # The bell is unaffected — only email delivery varies by recipient.
    assert resolve(bystander, "test_queue").in_app is True


@pytest.mark.django_db
def test_explicit_override_beats_the_role_default(monkeypatch):
    from notifications import categories as cats

    meta = cats.CategoryMeta(
        cats.SECTION_ACCOUNT, "Test queue",
        default_email_for=lambda u: EmailDelivery.OFF,
    )
    monkeypatch.setitem(cats.CATEGORY_META, "test_queue", meta)

    user = make_user("opted-in@x.co")
    pref = NotificationPreference.objects.create(user=user)
    pref.set("test_queue", in_app=True, email=EmailDelivery.IMMEDIATE)
    pref.save()

    user = User.objects.get(pk=user.pk)  # drop the cached relation
    assert resolve(user, "test_queue").email is True


@pytest.mark.django_db
def test_categories_without_a_role_default_are_unchanged():
    user = make_user("plain@x.co")
    assert resolve(user, Category.REGISTRATION_STATUS).email is True
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest notifications/tests.py -k "default_email_for or role_default or without_a_role" -v`
Expected: FAIL — `TypeError: CategoryMeta.__init__() got an unexpected keyword argument 'default_email_for'`.

- [ ] **Step 3: Add the field**

In `notifications/categories.py`, add the import and the field:

```python
from collections.abc import Callable
```

```python
@dataclass(frozen=True)
class CategoryMeta:
    section: str
    label: str
    help_text: str = ""
    default_in_app: bool = True
    default_email: str = EmailDelivery.IMMEDIATE
    # Email the member may not turn off (transactional/security).
    email_locked: bool = False
    # Whether this category can appear on each channel at all.
    in_app_capable: bool = True
    email_capable: bool = True
    # Optional per-recipient email default, consulted only when the member
    # hasn't chosen for themselves. Lets a queue aim its email at the role
    # that owns it while the rest of the committee keeps the bell row; both
    # sides can still override on the settings page.
    default_email_for: Callable[[object], str] | None = None
```

- [ ] **Step 4: Consult it in `resolve`**

In `notifications/preferences.py`, replace the default assignment:

```python
    in_app = meta.default_in_app
    email_choice = meta.default_email
    if meta.default_email_for is not None:
        email_choice = meta.default_email_for(user)
```

Also extend the module docstring's first paragraph to mention that a category may carry a per-recipient default.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest notifications/tests.py -v`
Expected: PASS (all of them — the mechanism is opt-in, so existing categories are untouched).

- [ ] **Step 6: Commit**

```bash
git add notifications/categories.py notifications/preferences.py notifications/tests.py
git commit -m "feat(notifications): per-recipient email defaults via CategoryMeta.default_email_for (task #491)"
```

---

### Task 2: Aim payment-plan review email at the Treasurer

**Files:**
- Modify: `notifications/categories.py` (the `TUITION_PLAN_REVIEW` entry, ~line 172)
- Test: Create `payments/test_plan_notification_routing.py`

**Interfaces:**
- Consumes: `CategoryMeta.default_email_for` from Task 1.
- Produces: `notifications.categories._tuition_plan_review_default(user) -> str`.

- [ ] **Step 1: Write the failing test**

Create `payments/test_plan_notification_routing.py`:

```python
"""Who gets emailed when a member applies for a tuition payment plan
(task #491).

The Board keeps the queue and the decision, but only the Treasurer is
emailed per application; the rest of the Board gets the bell row. Both
sides can still change it on the notification settings page.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from accounts.models import User
from committees.models import Committee
from core.models import StaffRole
from notifications.categories import Category, EmailDelivery
from notifications.models import Notification, NotificationPreference
from payments.models import TuitionPeriod, TuitionPlanApplication
from payments.notifications import notify_plan_application_submitted
from workgroups.models import WorkgroupMembership

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_seeded_periods():
    TuitionPeriod.objects.all().delete()


@pytest.fixture
def period():
    return TuitionPeriod.objects.create(
        name="AY 2026-2027", slug="ay-2026-2027",
        start_date=date(2026, 9, 1), end_date=date(2027, 6, 30),
        decision_due_date=date(2026, 10, 1),
        tuition_amount=Decimal("1000"),
    )


def _board(user):
    Committee.objects.get(slug="board").add_member(
        user, role=WorkgroupMembership.Role.MEMBER, start_date=date(2026, 1, 1),
    )
    return user


@pytest.fixture
def treasurer():
    u = _board(User.objects.create_user(email="plan-treasurer@x.test", password="x"))
    StaffRole.objects.get(key=StaffRole.TREASURER).holders.add(u)
    return u


@pytest.fixture
def board_member():
    return _board(User.objects.create_user(email="plan-board@x.test", password="x"))


@pytest.fixture
def application(period):
    applicant = User.objects.create_user(email="plan-applicant@x.test", password="x")
    applicant.profile.role = "candidate"
    applicant.profile.save()
    return TuitionPlanApplication.objects.create(
        user=applicant, tuition_period=period, reasons="Money is tight this year.",
    )


def test_treasurer_is_emailed_and_the_rest_of_the_board_is_not(
    treasurer, board_member, application, mailoutbox,
    django_capture_on_commit_callbacks,
):
    with django_capture_on_commit_callbacks(execute=True):
        notify_plan_application_submitted(application)

    # Both see it in the bell.
    for user in (treasurer, board_member):
        assert Notification.objects.filter(
            recipient=user, category=Category.TUITION_PLAN_REVIEW,
        ).exists()

    recipients = {addr for m in mailoutbox for addr in m.to}
    assert recipients == {treasurer.email}


def test_a_board_member_can_opt_into_the_email(
    treasurer, board_member, application, mailoutbox,
    django_capture_on_commit_callbacks,
):
    pref = NotificationPreference.objects.create(user=board_member)
    pref.set(Category.TUITION_PLAN_REVIEW, in_app=True, email=EmailDelivery.IMMEDIATE)
    pref.save()

    with django_capture_on_commit_callbacks(execute=True):
        notify_plan_application_submitted(application)

    recipients = {addr for m in mailoutbox for addr in m.to}
    assert recipients == {treasurer.email, board_member.email}


def test_the_treasurer_can_opt_out(
    treasurer, application, mailoutbox, django_capture_on_commit_callbacks,
):
    pref = NotificationPreference.objects.create(user=treasurer)
    pref.set(Category.TUITION_PLAN_REVIEW, in_app=True, email=EmailDelivery.OFF)
    pref.save()

    with django_capture_on_commit_callbacks(execute=True):
        notify_plan_application_submitted(application)

    assert mailoutbox == []


def test_with_no_treasurer_the_board_is_emailed(
    board_member, application, mailoutbox, django_capture_on_commit_callbacks,
):
    # An unassigned role must never mean an application sits unseen.
    StaffRole.objects.get(key=StaffRole.TREASURER).holders.clear()

    with django_capture_on_commit_callbacks(execute=True):
        notify_plan_application_submitted(application)

    recipients = {addr for m in mailoutbox for addr in m.to}
    assert recipients == {board_member.email}


def test_the_applicant_is_not_notified_as_a_reviewer(
    treasurer, application, mailoutbox, django_capture_on_commit_callbacks,
):
    _board(application.user)

    with django_capture_on_commit_callbacks(execute=True):
        notify_plan_application_submitted(application)

    assert not Notification.objects.filter(
        recipient=application.user, category=Category.TUITION_PLAN_REVIEW,
    ).exists()
```

- [ ] **Step 2: Run and watch it fail**

Run: `uv run pytest payments/test_plan_notification_routing.py -v`
Expected: FAIL — the whole Board is emailed, so `test_treasurer_is_emailed_and_the_rest_of_the_board_is_not` and `test_with_no_treasurer...` fail on the recipient set.

- [ ] **Step 3: Implement the role default**

In `notifications/categories.py`, above `CATEGORY_META`, add:

```python
def _tuition_plan_review_default(user) -> str:
    """Aim payment-plan application email at the Treasurer (task #491).

    The Board reviews and decides these applications, so everyone on it gets
    the bell row, but only the Treasurer needs an email per application. If
    nobody holds the role, fall back to emailing the Board — an unassigned
    role must never mean an application sits unseen.
    """
    from core.access import has_staff_role
    from core.models import StaffRole

    if has_staff_role(user, StaffRole.TREASURER):
        return EmailDelivery.IMMEDIATE
    held = StaffRole.objects.filter(
        key=StaffRole.TREASURER, holders__isnull=False,
    ).exists()
    return EmailDelivery.OFF if held else EmailDelivery.IMMEDIATE
```

Replace the `TUITION_PLAN_REVIEW` entry with:

```python
    _C.TUITION_PLAN_REVIEW: _M(
        SECTION_PAYMENTS, _("Tuition payment plans"),
        _("For the Treasurer and Board: a payment plan application to review. "
          "The Treasurer is emailed each application; the rest of the Board "
          "sees it in the bell, unless you turn email on here."),
        default_email=_E.OFF,
        default_email_for=_tuition_plan_review_default,
    ),
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest payments/test_plan_notification_routing.py -v`
Expected: PASS.

- [ ] **Step 5: Run the neighbouring suites for regressions**

Run: `uv run pytest payments/test_plan_review_queue.py payments/test_plan_application_models.py notifications/ -v`
Expected: PASS. If a queue test asserted the Board was emailed, update it to the new routing and note the change in the commit message.

- [ ] **Step 6: Commit**

```bash
git add notifications/categories.py payments/test_plan_notification_routing.py
git commit -m "feat(payments): email tuition plan applications to the Treasurer, bell-only for the Board (task #491)"
```

---

### Task 3: Split the applicant's decision onto its own category

**Files:**
- Modify: `notifications/categories.py` (the `Category` choices ~line 43, and `CATEGORY_META`)
- Modify: `payments/notifications.py` (`notify_plan_application_decided`, ~line 216)
- Test: `payments/test_plan_notification_routing.py`

**Interfaces:**
- Consumes: nothing from Tasks 1–2 beyond the category table.
- Produces: `Category.TUITION_PLAN_DECISION = "tuition_plan_decision"`.

- [ ] **Step 1: Write the failing test**

Append to `payments/test_plan_notification_routing.py`:

```python
def test_the_applicant_hears_the_decision_even_with_review_email_off(
    application, mailoutbox, django_capture_on_commit_callbacks,
):
    """The reviewer queue and the applicant's own outcome are separate
    categories — silencing the queue must not silence the applicant."""
    from payments.notifications import notify_plan_application_decided

    pref = NotificationPreference.objects.create(user=application.user)
    pref.set(Category.TUITION_PLAN_REVIEW, in_app=True, email=EmailDelivery.OFF)
    pref.save()

    application.status = TuitionPlanApplication.Status.APPROVED
    application.save(update_fields=["status"])

    with django_capture_on_commit_callbacks(execute=True):
        notify_plan_application_decided(application)

    row = Notification.objects.get(
        recipient=application.user, category=Category.TUITION_PLAN_DECISION,
    )
    assert "approved" in row.title.lower()
    assert [addr for m in mailoutbox for addr in m.to] == [application.user.email]
```

- [ ] **Step 2: Run and watch it fail**

Run: `uv run pytest payments/test_plan_notification_routing.py -k decision -v`
Expected: FAIL — `AttributeError: TUITION_PLAN_DECISION`.

- [ ] **Step 3: Add the category**

In `notifications/categories.py`, next to `TUITION_PLAN_REVIEW` in the `Category` choices:

```python
    TUITION_PLAN_DECISION = "tuition_plan_decision", _("Your payment plan application")
```

And in `CATEGORY_META`, directly after the `TUITION_PLAN_REVIEW` entry:

```python
    _C.TUITION_PLAN_DECISION: _M(
        SECTION_PAYMENTS, _("Your payment plan application"),
        _("The Board's decision on a tuition payment plan you applied for."),
    ),
```

- [ ] **Step 4: Point the decision notice at it**

In `payments/notifications.py`, in `notify_plan_application_decided`, change the `notify(...)` call's category from `Category.TUITION_PLAN_REVIEW` to `Category.TUITION_PLAN_DECISION`, and add a line to the docstring: the applicant's outcome is its own category so quieting the reviewer queue can't silence it.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest payments/ notifications/ -q`
Expected: PASS. Any existing test asserting the decision row's category must be updated to `TUITION_PLAN_DECISION`.

- [ ] **Step 6: Commit**

```bash
git add notifications/categories.py payments/notifications.py payments/test_plan_notification_routing.py
git commit -m "feat(notifications): split the plan-application decision onto its own category (task #491)"
```

---

### Task 4: Clear incidental `tuition_plan_review` overrides

**Files:**
- Create: `notifications/migrations/00NN_clear_incidental_plan_review_overrides.py` (next number after the app's current latest — check with `ls notifications/migrations/`)
- Test: `notifications/tests.py`

**Interfaces:**
- Consumes: the routing from Task 2.
- Produces: nothing importable.

Why: `notifications/views.py:94-112` writes an override for **every** category whenever a member saves the settings page. So any Board member who has ever saved their preferences carries an explicit `tuition_plan_review: immediate` entry that would beat the new role default, and they'd keep getting the mail. Dropping entries that merely match the old default restores "no override, use the role default"; a Board member who genuinely wants the email can set it again.

- [ ] **Step 1: Write the failing test**

Append to `notifications/tests.py`, substituting the migration's real
`00NN_` prefix in the `import_module` path:

```python
@pytest.mark.django_db
def test_incidental_plan_review_override_is_cleared_by_the_migration():
    from importlib import import_module

    from django.apps import apps as django_apps

    mod = import_module(
        "notifications.migrations.00NN_clear_incidental_plan_review_overrides"
    )

    incidental = make_user("incidental@x.co")
    NotificationPreference.objects.create(
        user=incidental,
        overrides={
            "tuition_plan_review": {"in_app": True, "email": "immediate"},
            "dues_reminder": {"in_app": True, "email": "immediate"},
        },
    )
    deliberate = make_user("deliberate@x.co")
    NotificationPreference.objects.create(
        user=deliberate,
        overrides={"tuition_plan_review": {"in_app": True, "email": "off"}},
    )

    mod.clear_incidental(django_apps, None)

    assert "tuition_plan_review" not in NotificationPreference.objects.get(
        user=incidental
    ).overrides
    # Unrelated categories are untouched.
    assert "dues_reminder" in NotificationPreference.objects.get(
        user=incidental
    ).overrides
    # A deliberate "off" is a real choice — leave it.
    assert NotificationPreference.objects.get(user=deliberate).overrides[
        "tuition_plan_review"
    ]["email"] == "off"
```

- [ ] **Step 2: Run and watch it fail**

Run: `uv run pytest notifications/tests.py -k incidental -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the migration**

```python
"""Drop `tuition_plan_review` overrides that merely echo the old default.

The settings page writes an entry for every category whenever a member
saves, so a stored ``immediate`` is not evidence anyone chose it — and it
would beat the new Treasurer-aware default (task #491), leaving the whole
Board on the mail. Removing those entries restores "no override, use the
role default"; a member who genuinely wants the email sets it again.

Deliberate non-default values (``off``, ``digest``) are left alone.
"""

from django.db import migrations

CATEGORY = "tuition_plan_review"
OLD_DEFAULT = "immediate"


def clear_incidental(apps, schema_editor):
    Preference = apps.get_model("notifications", "NotificationPreference")
    for pref in Preference.objects.all():
        overrides = pref.overrides or {}
        entry = overrides.get(CATEGORY)
        if isinstance(entry, dict) and entry.get("email") == OLD_DEFAULT:
            del overrides[CATEGORY]
            pref.overrides = overrides
            pref.save(update_fields=["overrides"])


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "<the app's current latest migration>"),
    ]

    operations = [
        migrations.RunPython(clear_incidental, migrations.RunPython.noop),
    ]
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest notifications/tests.py -k incidental -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add notifications/migrations/ notifications/tests.py
git commit -m "fix(notifications): clear incidental tuition_plan_review overrides so the Treasurer default applies (task #491)"
```

---

### Task 5: Rewrite the Tuition Assistance document

**Files:**
- Create: `documents/migrations/0012_tuition_assistance_is_the_payment_plan.py`
- Test: `documents/tests.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing importable.

Before writing the copy, verify the two claims the new text makes about a pending application, and drop or reword any that don't hold:

1. A `PLAN_REQUESTED` enrollment covers event registration at the tuition rate — check `payments/ledger.py` and the coverage helper on `accounts/models.py`.
2. `PLAN_REQUESTED` is skipped by balance reminders — check `payments/management/commands/send_balance_reminders.py:49`.

- [ ] **Step 1: Write the failing test**

Append to `documents/tests.py` (match the file's existing style for loading the document):

```python
@pytest.mark.django_db
def test_tuition_assistance_describes_the_payment_plan_application():
    doc = Document.objects.get(slug="tuition-assistance")
    body = doc.body

    # The old email-the-Treasurer procedure and the reduced-amount language
    # are gone (task #491: assistance IS the payment plan).
    assert "mailto:treasurer@lacanschool.org" not in body
    assert "symbolic contribution" not in body
    assert "No special authorization is needed" not in body

    # The site process is described.
    assert "apply to the Board for a payment plan" in body
    assert "/formation/?tab=account" in body
    assert "September and February" in body
```

- [ ] **Step 2: Run and watch it fail**

Run: `uv run pytest documents/tests.py -k tuition_assistance -v`
Expected: FAIL on the `mailto:` assertion.

- [ ] **Step 3: Write the migration**

Create `documents/migrations/0012_tuition_assistance_is_the_payment_plan.py`, following `0011_tuition_assistance_account_tab.py` exactly in shape (module docstring, `SLUG`, `BODY`, a `RunPython` function setting `body` and clearing `file`, reverse `noop`, dependency on `0011`). Body:

```
Tuition supports the School and your formation within it. This page explains how tuition is paid, and how to apply for a payment plan if paying the year at once is not workable for you.

## Paying your tuition

Each academic year, record your tuition decision on your [My LSP Account page](/formation/?tab=account). You can pay the full year at once, apply to the Board for a payment plan, or skip the year, and the page keeps a record of the decision you chose and when.

- **Pay in full** in September.
- **Apply for a payment plan** if paying the year at once is not workable, whether because of an exceptional situation, hardship, or living in a country with different wages and costs of living. See "Applying for a payment plan" below.
- **Skip the year.** Your four years of tuition need not be consecutive, so you may skip a year and resume later. While skipping, you pay the regular per-event fee for seminars rather than the covered-by-tuition rate.

Your [My LSP Account page](/formation/?tab=account) also shows your statement: every charge and payment on your account, with a running balance.

If your payments fall short, you will receive a reminder to pay the balance; if tuition remains unpaid after reminders, the administrator raises the matter with the Board.

It remains each member's responsibility to keep their own record of tuition payments. If you find a payment or a fee from before this website that your account does not show, you can report it from your Account page and the Treasurer will review it.

## Applying for a payment plan

A payment plan spreads the year's tuition across the year. It is what the School has also called tuition assistance: one process, applied for and recorded on the site.

Before applying, discuss your situation with your advisor and agree on a plan. Then:

1. On your [My LSP Account page](/formation/?tab=account), choose "I want to apply to the Board for a payment plan" and tell the Board briefly about your circumstances.
2. The Treasurer is notified, and the Board discusses your application at one of their next meetings, usually one to two months after you apply.
3. You are notified of the Board's decision on the site and by email.

While your application is pending, your tuition decision counts as made, so seminars you register for stay covered at the tuition rate.

If the Board approves your application, choose your schedule on your Account page: two payments, in September and February, or nine monthly payments from September through May. The installments together come to the year's full tuition, and you can pay each one from that page.

If the Board is unable to approve your application, your tuition decision opens again so you can choose to pay in full or skip the year.

A few things to keep in mind:

- Apply for each year in which you need a payment plan.
- Keep your own record of your payments and of any exceptions the Board grants.
```

Note: the document's `title` is deliberately unchanged. Members and existing links know it as Tuition Assistance, and the body now states the equivalence.

- [ ] **Step 4: Run the test**

Run: `uv run pytest documents/ -v`
Expected: PASS.

- [ ] **Step 5: Check the rendered markdown**

The doc renders through `render_doc`. Confirm no wrapped line inside a list item starts with `+`, `-`, or `*` (it would silently become a nested bullet), and that the copy uses commas rather than em dashes.

- [ ] **Step 6: Commit**

```bash
git add documents/migrations/0012_tuition_assistance_is_the_payment_plan.py documents/tests.py
git commit -m "docs(documents): tuition assistance is the payment plan application (task #491)"
```

---

### Task 6: Full verification

- [ ] **Step 1: Migrations are complete**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected". The `CategoryMeta` change is not a model change, so nothing new should appear.

- [ ] **Step 2: Apply migrations locally**

Run: `uv run python manage.py migrate`
Expected: the two new data migrations apply cleanly.

- [ ] **Step 3: Full suite + lint**

Run: `uv run pytest -q && uv run ruff check .`
Expected: both green. Fix anything that isn't before continuing.

- [ ] **Step 4: Eyeball the settings page**

Run the dev server and load `/notifications/settings/` as a Treasurer and as a plain member. Expected: "Tuition payment plans" shows *Email me* for the Treasurer and *No email* for everyone else, and "Your payment plan application" appears under Registration & payments.

- [ ] **Step 5: Commit anything outstanding, then report**

Summarize for the user: routing change, category split, the override-clearing migration, and the doc rewrite, plus the fact that deploying requires a green CI run (pushing to main is not deploying).
