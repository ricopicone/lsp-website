# Event-AY Tuition Gate + Payment Due Dates (Phases A+C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Registration gate + covered-by-tuition pricing key on the tuition period of the **event's** academic year, and tuition gains a payment-due date (Nov 30) distinct from the decision-due date (Oct 31).

**Architecture:** A tiny resolver (`payments.ledger.period_for_event`) anchors period lookups to `event.start_date`; the existing `on_date` parameters on `Profile.is_tuition_current` / `current_tuition_enrollment` and `TuitionPeriod.current` do the rest. The member decision endpoint accepts a period slug (current or next); the Account tab renders one decision block per open period. A new nullable `TuitionPeriod.payment_due_date` drives the committed-but-unpaid reminder cadence.

**Tech Stack:** Django 5.2, pytest-django, existing payments/registrations/formation apps.

## Global Constraints

- Member-facing copy uses commas, never em dashes (site-copy convention).
- Templates use DaisyUI semantic tokens only (`bg-base-100`, `text-primary`, …).
- `uv run pytest` and `uv run ruff check .` green before every commit; push to main deploys.
- Do-not-over-automate: no behavior removes staff override paths.
- Spec: `docs/superpowers/specs/2026-07-22-tuition-fall-launch-design.md`.

---

### Task 1: `TuitionPeriod.payment_due_date` field (Phase C)

**Files:**
- Modify: `payments/models.py` (TuitionPeriod, after `decision_due_date`, ~line 366)
- Create: `payments/migrations/00XX_tuitionperiod_payment_due_date.py` (makemigrations)

**Interfaces:**
- Produces: `TuitionPeriod.payment_due_date: date | None` — Task 2 reads it.

- [ ] **Step 1: Add the field**

```python
    payment_due_date = models.DateField(
        null=True, blank=True,
        help_text=(
            "Tuition payment due by this date (unpaid-committed reminders "
            "escalate after it; decision reminders key off decision_due_date)."
        ),
    )
```

- [ ] **Step 2: `uv run python manage.py makemigrations payments`** — expect one AddField migration.
- [ ] **Step 3: `uv run pytest payments/ -q`** — expect green (field is nullable, nothing breaks).
- [ ] **Step 4: Commit** `feat(payments): TuitionPeriod.payment_due_date (task #450 phase C)`

### Task 2: Reminders respect payment_due_date (Phase C)

**Files:**
- Modify: `payments/management/commands/send_tuition_reminders.py` (`_needs_reminder`, `handle`)
- Create: `payments/test_tuition_reminder_dates.py`

**Interfaces:**
- Consumes: `TuitionPeriod.payment_due_date` (Task 1).
- Behavior: undecided members remind after `decision_due_date` (unchanged); COMMITTED-but-unpaid remind only after `payment_due_date or decision_due_date`.

- [ ] **Step 1: Write failing tests**

```python
"""Committed-unpaid tuition reminders wait for payment_due_date."""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from freezegun import freeze_time  # if unavailable: monkeypatch timezone.now

from payments.models import TuitionEnrollment, TuitionPeriod

User = get_user_model()


@pytest.fixture
def period(db):
    return TuitionPeriod.objects.create(
        name="AY 2026–2027", slug="ay-2026-2027-tuition",
        start_date=date(2026, 9, 1), decision_due_date=date(2026, 10, 31),
        payment_due_date=date(2026, 11, 30), end_date=date(2027, 8, 31),
        tuition_amount=Decimal("2500"),
    )


@pytest.fixture
def student(db):
    u = User.objects.create_user(email="s@example.com", password="x")
    u.profile.role = "pre_candidate"
    u.profile.save(update_fields=["role"])
    return u


@pytest.mark.django_db
def test_committed_not_reminded_before_payment_due(period, student, mailoutbox, settings):
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    TuitionEnrollment.objects.create(
        user=student, tuition_period=period,
        status=TuitionEnrollment.Status.COMMITTED,
    )
    with freeze_time("2026-11-15"):
        call_command("send_tuition_reminders")
    assert len(mailoutbox) == 0


@pytest.mark.django_db
def test_committed_reminded_after_payment_due(period, student, mailoutbox, settings):
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    TuitionEnrollment.objects.create(
        user=student, tuition_period=period,
        status=TuitionEnrollment.Status.COMMITTED,
    )
    with freeze_time("2026-12-01"):
        call_command("send_tuition_reminders")
    assert len(mailoutbox) == 1


@pytest.mark.django_db
def test_undecided_reminded_after_decision_due(period, student, mailoutbox, settings):
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    with freeze_time("2026-11-15"):
        call_command("send_tuition_reminders")
    assert len(mailoutbox) == 1
```

(Confirm freezegun is a dependency first: `grep freezegun pyproject.toml`; if absent, monkeypatch `django.utils.timezone.now` in the tests instead — do not add a dependency.)

- [ ] **Step 2: Run** `uv run pytest payments/test_tuition_reminder_dates.py -q` — expect the committed-before-due test to FAIL (reminded too early today).
- [ ] **Step 3: Implement** — `_needs_reminder(enrollment, today, period)`:

```python
def _needs_reminder(enrollment, today, period) -> bool:
    if enrollment is None:
        return True  # no decision yet (decision_due gating happens in handle())
    if enrollment.status == TuitionEnrollment.Status.PAID_IN_FULL:
        return False
    if enrollment.status == TuitionEnrollment.Status.SKIPPING:
        return False
    if enrollment.status == TuitionEnrollment.Status.COMMITTED:
        pay_due = period.payment_due_date or period.decision_due_date
        return today > pay_due
    if enrollment.status == TuitionEnrollment.Status.PAYMENT_PLAN:
        return enrollment.installments.filter(paid=False, due_date__lte=today).exists()
    return False
```

Update the call site in `handle()` to pass `period`.

- [ ] **Step 4: Run** the new tests + `uv run pytest payments/ -q` — expect PASS.
- [ ] **Step 5: Commit** `feat(payments): committed-unpaid tuition reminders wait for payment_due_date (task #450 phase C)`

### Task 3: `period_for_event` resolver (Phase A)

**Files:**
- Modify: `payments/ledger.py` (new function, top-level)
- Create: `payments/test_period_for_event.py`

**Interfaces:**
- Produces: `period_for_event(event) -> TuitionPeriod | None` — Tasks 4–5 consume.

- [ ] **Step 1: Failing test**

```python
from datetime import date
from decimal import Decimal

import pytest

from events.models import Event
from payments.ledger import period_for_event
from payments.models import TuitionPeriod


@pytest.mark.django_db
def test_event_resolves_to_its_ay_period():
    p26 = TuitionPeriod.objects.create(
        name="AY 2026–2027", slug="t26", start_date=date(2026, 9, 1),
        decision_due_date=date(2026, 10, 31), end_date=date(2027, 8, 31),
        tuition_amount=Decimal("2500"),
    )
    e = Event.objects.create(
        title="X", slug="x", start_date=date(2026, 9, 15), end_date=date(2027, 6, 1),
    )
    assert period_for_event(e) == p26


@pytest.mark.django_db
def test_undated_event_falls_back_to_today():
    e = Event.objects.create(title="Y", slug="y")
    assert period_for_event(e) is None  # no periods exist at all
```

- [ ] **Step 2: Run** — FAIL (ImportError).
- [ ] **Step 3: Implement** in `payments/ledger.py`:

```python
def period_for_event(event):
    """The TuitionPeriod an event belongs to.

    Annual-program events anchor to their start_date; undated or one-off
    events fall back to the period containing today (matching the old
    behavior for special events and Days of Assembly).
    """
    from payments.models import TuitionPeriod

    anchor = getattr(event, "start_date", None)
    return TuitionPeriod.current(on_date=anchor)  # anchor=None -> today
```

- [ ] **Step 4: Run** — PASS. **Step 5: Commit** `feat(payments): period_for_event resolver (task #450 phase A)`

### Task 4: Gate keys on the event's period (Phase A)

**Files:**
- Modify: `registrations/views.py:_tuition_block_reason` (~line 99)
- Test: extend `registrations/` tests — create `registrations/test_event_ay_gate.py`

**Interfaces:**
- Consumes: `period_for_event` (Task 3).

- [ ] **Step 1: Failing test** — in-training member with a 2025-26 decision but no 2026-27 row is blocked from a Sept-2026 event; adding a 26-27 SKIPPING row unblocks:

```python
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from events.models import Event
from payments.models import TuitionEnrollment, TuitionPeriod
from registrations.views import _tuition_block_reason

User = get_user_model()


@pytest.fixture
def periods(db):
    mk = lambda y: TuitionPeriod.objects.create(
        name=f"AY {y}–{y+1}", slug=f"t{y}", start_date=date(y, 9, 1),
        decision_due_date=date(y, 10, 31), end_date=date(y + 1, 8, 31),
        tuition_amount=Decimal("2500"),
    )
    return mk(2025), mk(2026)


@pytest.fixture
def student(db):
    u = User.objects.create_user(email="s2@example.com", password="x")
    u.profile.role = "candidate"
    u.profile.save(update_fields=["role"])
    return u


@pytest.mark.django_db
def test_gate_demands_the_events_ay_decision(periods, student):
    p25, p26 = periods
    TuitionEnrollment.objects.create(
        user=student, tuition_period=p25,
        status=TuitionEnrollment.Status.PAID_IN_FULL,
    )
    event = Event.objects.create(
        title="Fall", slug="fall", start_date=date(2026, 9, 15),
        end_date=date(2027, 6, 1),
    )
    reason = _tuition_block_reason(student, event)
    assert reason is not None and "2026–2027" in reason

    TuitionEnrollment.objects.create(
        user=student, tuition_period=p26,
        status=TuitionEnrollment.Status.SKIPPING,
    )
    assert _tuition_block_reason(student, event) is None
```

- [ ] **Step 2: Run** — FAIL (gate passes on the 25-26 row today, July 2026… note: test runs "today"=real date; the gate under test must use the event anchor, so the assertion holds regardless of run date once implemented; before implementation it fails because current() in CI (2026-07) is p25… if CI date drifts past 2026-08-31 revisit fixtures).
- [ ] **Step 3: Implement** — in `_tuition_block_reason`, replace:

```python
    from payments.models import TuitionEnrollment, TuitionPeriod
    period = TuitionPeriod.current()
    if period is None:
        return None
    enr = profile.current_tuition_enrollment()
```

with:

```python
    from payments.ledger import period_for_event
    from payments.models import TuitionEnrollment
    period = period_for_event(event)
    if period is None:
        return None
    enr = TuitionEnrollment.objects.filter(
        user=user, tuition_period=period,
    ).first()
```

(The block messages already interpolate `period.name`, so they follow automatically.)

- [ ] **Step 4: Run** new + `uv run pytest registrations/ -q` — PASS. **Step 5: Commit** `feat(registrations): tuition gate keys on the event's academic year (task #450 phase A)`

### Task 5: Coverage keys on the event's period (Phase A)

**Files:**
- Modify: `registrations/views.py:_find_covered_tier` (~line 47) and every `is_tuition_current()` call in the register flow (`grep -n "is_tuition_current" registrations/ events/`)
- Test: add to `registrations/test_event_ay_gate.py`

**Interfaces:**
- Consumes: `Profile.is_tuition_current(on_date)` (exists), event anchor.

- [ ] **Step 1: Failing test** — a member covered for 25-26 gets NO covered tier on a 26-27 event until a covering 26-27 enrollment exists:

```python
@pytest.mark.django_db
def test_coverage_requires_the_events_ay(periods, student):
    from events.models import Audience, PriceTier
    from registrations.views import _find_covered_tier

    p25, p26 = periods
    TuitionEnrollment.objects.create(
        user=student, tuition_period=p25,
        status=TuitionEnrollment.Status.PAID_IN_FULL,
    )
    event = Event.objects.create(
        title="Fall2", slug="fall2", start_date=date(2026, 9, 15),
        end_date=date(2027, 6, 1),
    )
    PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("200"),
        covered_by_tuition=True,
    )
    assert _find_covered_tier(student, event) is None

    TuitionEnrollment.objects.create(
        user=student, tuition_period=p26,
        status=TuitionEnrollment.Status.PAID_IN_FULL,
    )
    assert _find_covered_tier(student, event) is not None
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** — in `_find_covered_tier`:

```python
    if not (profile and profile.is_tuition_current(
        getattr(event, "start_date", None)
    )):
        return None
```

Then sweep the register view/template context for other `is_tuition_current()` calls tied to a specific event and pass the same anchor (`grep -n "is_tuition_current" registrations/views.py events/views.py` — update each event-scoped call; leave non-event calls, e.g. directory badges, on today).

- [ ] **Step 4: Run** suites — PASS. **Step 5: Commit** `feat(registrations): covered-by-tuition keys on the event's academic year (task #450 phase A)`

### Task 6: Decision UI covers the upcoming period (Phase A)

**Files:**
- Modify: `payments/views.py:tuition_decision` (~line 2188)
- Modify: the formation hub account-tab context (`formation/views.py`, the view rendering `_tab_account.html`)
- Modify: `formation/templates/formation/_tab_account.html`
- Test: create `payments/test_tuition_decision_periods.py`

**Interfaces:**
- POST `tuition_decision` gains optional `period` (slug); valid values: the current period and the next-by-start_date future period. Missing/invalid slug → current (backcompat).

- [ ] **Step 1: Failing test**

```python
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from payments.models import TuitionEnrollment, TuitionPeriod

User = get_user_model()


@pytest.mark.django_db
def test_member_can_record_upcoming_year_decision(client):
    # Periods: one containing today, one future.
    import datetime
    today = datetime.date.today()
    cur = TuitionPeriod.objects.create(
        name="Cur", slug="cur", start_date=today.replace(month=1, day=1),
        decision_due_date=today, end_date=today.replace(month=12, day=31),
        tuition_amount=Decimal("2500"),
    )
    nxt = TuitionPeriod.objects.create(
        name="Next", slug="next",
        start_date=today.replace(year=today.year + 1, month=1, day=1),
        decision_due_date=today.replace(year=today.year + 1),
        end_date=today.replace(year=today.year + 1, month=12, day=31),
        tuition_amount=Decimal("2500"),
    )
    u = User.objects.create_user(email="d@example.com", password="x")
    u.profile.role = "candidate"
    u.profile.save(update_fields=["role"])
    client.force_login(u)

    client.post(reverse("tuition_decision"), {"status": "skipping", "period": "next"})
    assert TuitionEnrollment.objects.filter(user=u, tuition_period=nxt).exists()
    assert not TuitionEnrollment.objects.filter(user=u, tuition_period=cur).exists()
```

- [ ] **Step 2: Run** — FAIL (period param ignored; row lands on current). **Step 3: Implement** in `tuition_decision`:

```python
    period = TuitionPeriod.current()
    requested = request.POST.get("period", "")
    if requested:
        upcoming = (
            TuitionPeriod.objects.filter(start_date__gt=timezone.now().date())
            .order_by("start_date").first()
        )
        allowed = {p.slug: p for p in (period, upcoming) if p is not None}
        period = allowed.get(requested, period)
```

- [ ] **Step 4:** Formation account-tab context: where the view supplies the decision panel data, add `upcoming_period` (same "next future period" query) + `upcoming_enrollment` (member's row for it, may be None), and render a second decision block in `_tab_account.html` mirroring the current-period block, with `<input type="hidden" name="period" value="{{ upcoming_period.slug }}">` and heading "Your {{ upcoming_period.name }} tuition decision". Match existing DaisyUI classes; commas not em dashes in copy.
- [ ] **Step 5: Run** `uv run pytest payments/ formation/ -q` + view the tab locally (`npm run build:css` if template classes changed). **Step 6: Commit** `feat(payments,formation): record the upcoming year's tuition decision (task #450 phase A)`

### Task 7: Prod data + verification (post-deploy)

- [ ] **Step 1:** After the deploy goes green, via SSM: set `payment_due_date=date(2026, 11, 30)` on the AY 2026–2027 TuitionPeriod (shell one-liner, `update_fields`).
- [ ] **Step 2:** Verify on prod: the Account tab shows both decision blocks for an in-training member; `_tuition_block_reason` demo via a staff-side check or test registration on a draft event preview.
- [ ] **Step 3:** Update the task #450 briefing; registration can open (PC flips event statuses) once this lands.

## Self-review notes

- Spec A: resolver (T3), gate (T4), coverage (T5), Account tab (T6) — covered. Spec C: field (T1), reminders (T2), prod date (T7) — covered.
- Phase B and D are separate plans (not started).
- Type consistency: `period_for_event(event)` consumed in T4/T5 as defined in T3; `payment_due_date` optional everywhere it's read.
