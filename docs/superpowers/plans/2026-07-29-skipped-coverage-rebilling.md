# Re-bill event fees when a covered year is skipped — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recording SKIPPING for an academic year re-bills the tuition-covered registrations in that year at the regular fee, warning the member first; recording a paying decision un-bills them.

**Architecture:** One new module, `payments/coverage.py`, owns the whole question — which registrations tuition coverage paid for in a year, what each is worth, and how to bill or un-bill them. It has no view logic and no notification logic. `payments/views.py::tuition_decision` is the only wiring point: it gains a POST-confirm interstitial before recording SKIPPING and calls bill/un-bill after recording. Billing works by **re-quoting the existing Registration** (`quoted_amount` + status), which reuses the built Stripe "Pay →" button, the registration reminders, and `mint_registration_charge` at settle, rather than minting a bare Charge nobody can pay.

**Tech Stack:** Django 5.2, pytest-django, Django templates (DaisyUI semantic tokens).

**Spec:** `docs/superpowers/specs/2026-07-29-skipped-coverage-rebilling-design.md`
**Task:** #485 (follow-on to #484)

## Global Constraints

- **No migration and no new model field.** The marker for "this was re-billed" is the `quoted_explanation` string, held in the module constant `REBILLED_EXPLANATION` — exactly how `"Covered by tuition (tuition-paying member, REG-4)"` already identifies a covered registration. A test pins it.
- **Status moves only for a PAID row.** A `PENDING_APPROVAL` row gets its amount rewritten and **keeps its status**, because `Registration.approve()` routes on the amount ($0 → PAID, nonzero → AWAITING_PAYMENT). Flipping it directly would skip the faculty approval it is waiting for.
- **Never touch a paid row.** `unbill_skipped_coverage` leaves any registration the member actually paid alone; that is a treasurer refund conversation.
- **Staff paths must not auto-bill** — Django admin, the treasurer's inline set-status, `backfill_tuition_status`, and the importers. Wiring goes in `tuition_decision` only. A historical backfill that retro-billed years of events would be a disaster.
- **Member-facing copy uses commas, not em dashes** (2026-07-06 convention). Code comments and in-repo docs use unspaced em dashes.
- **Templates use DaisyUI semantic tokens** (`text-base-content`, `bg-base-200`, `alert-warning`, …), never hardcoded colors.
- Run tests with `uv run pytest`, lint with `uv run ruff check .`. Both green before the final commit.
- Registration statuses are `pending_approval`, `awaiting_payment`, `paid`, `comped`, `declined`, `cancelled`, `refunded` (`registrations/models.py:13-20`).

## File Structure

| File | Responsibility |
|---|---|
| `payments/coverage.py` (new) | What coverage gave a member in a year, what it is worth, and bill/un-bill. Pure model work, no views, no notifications. |
| `payments/test_coverage.py` (new) | Unit tests for the module above. |
| `payments/views.py` (modify `tuition_decision`) | The confirm interstitial and the two calls. |
| `payments/templates/payments/skip_confirm.html` (new) | The warning page listing events, fees, and total. |
| `payments/notifications.py` (modify) | `coverage_rebilled(...)` notification; rewrite the decline body from #484. |
| `registrations/templates/registrations/register_confirm.html` (modify) | One line explaining why a covered place now wants money. |
| `payments/test_tuition.py`, `payments/test_plan_review_queue.py` (modify) | View-level and notification tests. |
| `core/docs/treasurer-guide.md`, `CLAUDE.md` (modify) | Policy docs. |

---

### Task 1: `payments/coverage.py` — what coverage bought, and what it is worth

**Files:**
- Create: `payments/coverage.py`
- Test: `payments/test_coverage.py` (new)

**Interfaces:**
- Consumes: `payments.ledger.period_for_event(event)` → `TuitionPeriod | None` (`payments/ledger.py:532`).
- Produces, for Tasks 2-4:
  - `REBILLED_EXPLANATION: str`
  - `COVERED_EXPLANATION: str` (the existing covered wording, so un-billing can restore it)
  - `retro_amount(tier) -> Decimal`
  - `covered_registrations(user, period) -> list[Registration]`

- [ ] **Step 1: Write the failing tests**

Create `payments/test_coverage.py`. The fixtures are local and deliberate: a candidate, a tuition period, and events inside/outside it.

```python
"""Coverage re-billing (task #485) — what tuition coverage bought a member in a
year, and what each of those registrations is worth if the year ends up skipped."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from accounts.models import Profile, User
from events.models import Audience, Event, PriceTier
from payments import coverage
from payments.models import TuitionPeriod
from registrations.models import Registration

pytestmark = pytest.mark.django_db


@pytest.fixture
def period():
    TuitionPeriod.objects.all().delete()   # seed migration pre-populates periods
    return TuitionPeriod.objects.create(
        name="AY 2026–2027", slug="ay-2026-2027-cov",
        start_date=date(2026, 9, 1), decision_due_date=date(2026, 10, 31),
        end_date=date(2027, 8, 31), tuition_amount=Decimal("800.00"),
    )


@pytest.fixture
def student():
    u = User.objects.create_user(email="cov-student@x.test", password="x")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.save()
    return u


def _event(slug, start=date(2026, 10, 1)):
    return Event.objects.create(
        title=slug.title(), slug=slug, start_date=start, end_date=start,
        status=Event.Status.OPEN, published=True,
    )


def _tier(event, *, amount="200.00", covered=True, sliding=False, minimum="0.00"):
    return PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal(amount),
        covered_by_tuition=covered, sliding_scale=sliding,
        minimum_amount=Decimal(minimum),
    )


def _reg(student, tier, *, status=Registration.Status.PAID, amount="0.00", code=None):
    return Registration.objects.create(
        user=student, event=tier.event, price_tier=tier, pricing_code=code,
        quoted_amount=Decimal(amount),
        quoted_explanation=coverage.COVERED_EXPLANATION,
        status=status,
    )


def test_retro_amount_is_the_listed_price_for_a_flat_tier(period):
    tier = _tier(_event("flat"), amount="200.00")
    assert coverage.retro_amount(tier) == Decimal("200.00")


def test_retro_amount_is_the_floor_for_a_sliding_tier(period):
    """A skipping member would have picked their own figure at or above the
    floor, so assume the floor rather than the top."""
    tier = _tier(_event("slide"), amount="200.00", sliding=True, minimum="60.00")
    assert coverage.retro_amount(tier) == Decimal("60.00")


def test_covered_registrations_finds_a_covered_zero_registration(period, student):
    reg = _reg(student, _tier(_event("seminar-a")))
    assert coverage.covered_registrations(student, period) == [reg]


def test_covered_registrations_excludes_another_academic_year(period, student):
    _reg(student, _tier(_event("last-year", start=date(2025, 10, 1))))
    assert coverage.covered_registrations(student, period) == []


def test_covered_registrations_excludes_a_comp(period, student):
    """A comp is already charge-backed by mint_comped_charge, and it is not
    tuition coverage."""
    _reg(student, _tier(_event("comped")), status=Registration.Status.COMPED)
    assert coverage.covered_registrations(student, period) == []


def test_covered_registrations_excludes_a_pricing_code_freebie(period, student):
    """A code that zeroed the fee is not tuition coverage. PricingCode has no
    "free" mode — 100 percent off is how a free code is expressed."""
    from events.models import PricingCode

    tier = _tier(_event("codefree"))
    code = PricingCode.objects.create(
        event=tier.event, code="FREE-1", issued_by=student,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("100"),
    )
    _reg(student, tier, code=code)
    assert coverage.covered_registrations(student, period) == []


def test_covered_registrations_excludes_a_cancelled_registration(period, student):
    _reg(student, _tier(_event("gone")), status=Registration.Status.CANCELLED)
    assert coverage.covered_registrations(student, period) == []


def test_covered_registrations_excludes_a_paid_nonzero_registration(period, student):
    """Someone who paid the regular fee owes nothing extra."""
    _reg(student, _tier(_event("paidfor")), amount="200.00")
    assert coverage.covered_registrations(student, period) == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest payments/test_coverage.py -q -p no:randomly`
Expected: collection error — `ModuleNotFoundError: No module named 'payments.coverage'`.

If `PricingCode.Mode.FREE` does not exist, run `grep -n "class Mode" -A 6 events/models.py` and use the free-equivalent member name it defines; do not invent one.

- [ ] **Step 3: Write the module**

Create `payments/coverage.py`:

```python
"""What tuition coverage bought a member in an academic year (task #485).

A registration priced at $0 because the member's tuition covers it leaves no
Payment and no Charge — ``mint_registration_charge`` requires a positive amount
— so it is invisible to the ledger. That is correct while the year is being
paid for. It stops being correct the moment the year is skipped: the member
keeps the events for free.

This module answers three questions and nothing else: which registrations
coverage paid for in a period, what each would have cost, and how to bill or
un-bill them. Wiring lives in ``payments.views.tuition_decision``; staff paths
deliberately do not auto-bill (a historical backfill would retro-bill years of
events).
"""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

#: The explanation a tuition-covered registration carries. Matches the string
#: written by ``registrations.views.register_for_event``'s covered short-circuit
#: — keep them identical.
COVERED_EXPLANATION = "Covered by tuition (tuition-paying member, REG-4)."

#: The explanation a re-billed registration carries. Doubles as the marker
#: ``unbill_skipped_coverage`` matches on, so no model field is needed.
REBILLED_EXPLANATION = (
    "Regular fee: tuition coverage no longer applies (tuition skipped this year)."
)


def retro_amount(tier) -> Decimal:
    """What a covered registration on ``tier`` is worth without coverage.

    A ``covered_by_tuition`` tier is the same tier non-paying members buy, so
    its ``base_amount`` is the regular fee. On a sliding tier the member would
    have chosen their own figure at or above the floor, so assume the floor.
    """
    if tier.sliding_scale:
        return tier.minimum_amount or Decimal("0")
    return tier.base_amount or Decimal("0")


def covered_registrations(user, period) -> list:
    """The member's registrations that tuition coverage paid for in ``period``.

    Excludes comps (already charge-backed by ``mint_comped_charge``),
    pricing-code freebies (not coverage), and anything cancelled or refunded.
    """
    from payments.ledger import period_for_event
    from registrations.models import Registration

    if period is None:
        return []
    rows = (
        Registration.objects
        .filter(
            user=user,
            price_tier__covered_by_tuition=True,
            pricing_code__isnull=True,
            quoted_amount=Decimal("0"),
            status__in=(
                Registration.Status.PAID,
                Registration.Status.PENDING_APPROVAL,
            ),
        )
        .select_related("event", "price_tier")
        .order_by("event__start_date", "pk")
    )
    return [r for r in rows if period_for_event(r.event) == period]


def bill_skipped_coverage(user, period) -> list:
    """Re-quote each covered registration in ``period`` at the regular fee.

    Idempotent — a row already carrying ``REBILLED_EXPLANATION`` is skipped
    (``covered_registrations`` only returns $0 rows, so a billed row cannot
    reappear). Returns the rows changed.
    """
    from registrations.models import Registration

    today = timezone.now().date()
    changed = []
    for reg in covered_registrations(user, period):
        amount = retro_amount(reg.price_tier)
        if amount <= 0:
            continue                     # a free tier owes nothing
        reg.quoted_amount = amount
        reg.quoted_explanation = REBILLED_EXPLANATION
        # Only a PAID row moves. approve() routes a PENDING_APPROVAL row on the
        # amount, so flipping it here would skip the faculty approval it awaits.
        if reg.status == Registration.Status.PAID:
            reg.status = Registration.Status.AWAITING_PAYMENT
        reg.staff_notes = (
            f"{reg.staff_notes}\n[{today}] Re-billed ${amount} for "
            f"{period.name}: tuition skipped, so coverage no longer applies "
            "(task #485)."
        ).strip()
        reg.save(update_fields=(
            "quoted_amount", "quoted_explanation", "status", "staff_notes",
        ))
        changed.append(reg)
    return changed


def unbill_skipped_coverage(user, period) -> list:
    """Undo ``bill_skipped_coverage`` for rows still unpaid.

    Restores coverage pricing when the member records a paying decision, so
    committing to pay tuition returns their access without any money moving. A
    row the member actually paid is left alone: that is a refund conversation
    for the treasurer, never a silent unwind.
    """
    from payments.ledger import period_for_event
    from registrations.models import Registration

    if period is None:
        return []
    today = timezone.now().date()
    changed = []
    rows = (
        Registration.objects
        .filter(
            user=user,
            quoted_explanation=REBILLED_EXPLANATION,
            status__in=(
                Registration.Status.AWAITING_PAYMENT,
                Registration.Status.PENDING_APPROVAL,
            ),
        )
        .select_related("event", "price_tier")
    )
    for reg in rows:
        if period_for_event(reg.event) != period:
            continue
        reg.quoted_amount = Decimal("0")
        reg.quoted_explanation = COVERED_EXPLANATION
        if reg.status == Registration.Status.AWAITING_PAYMENT:
            reg.status = Registration.Status.PAID
        reg.staff_notes = (
            f"{reg.staff_notes}\n[{today}] Coverage restored for "
            f"{period.name}: tuition is being paid again (task #485)."
        ).strip()
        reg.save(update_fields=(
            "quoted_amount", "quoted_explanation", "status", "staff_notes",
        ))
        changed.append(reg)
    return changed
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest payments/test_coverage.py -q -p no:randomly`
Expected: all PASS.

- [ ] **Step 5: Confirm the covered-explanation string really matches the app**

Run: `grep -rn "Covered by tuition (tuition-paying member, REG-4)" --include=*.py .`
Expected: hits in `registrations/views.py`, `events/pricing.py`, and `payments/coverage.py`, all identical. If the app's string differs by so much as a period, change `COVERED_EXPLANATION` to match the app — the app is the source of truth.

- [ ] **Step 6: Commit**

```bash
git add payments/coverage.py payments/test_coverage.py
git commit -m "feat(payments): module for what tuition coverage bought in a year (#485)"
```

---

### Task 2: Bill on skip, un-bill on a paying decision

**Files:**
- Modify: `payments/coverage.py` (no change — Task 1 wrote both functions; this task tests them at the model level)
- Test: `payments/test_coverage.py` (append)

**Interfaces:**
- Consumes: `coverage.bill_skipped_coverage(user, period)`, `coverage.unbill_skipped_coverage(user, period)`, `coverage.REBILLED_EXPLANATION`, and the fixtures/helpers from Task 1 (`period`, `student`, `_event`, `_tier`, `_reg`).
- Produces: nothing new. This task proves the two functions behave, including the two rules a later reviewer will care about most: PENDING_APPROVAL keeps its status, and a paid row is never unwound.

- [ ] **Step 1: Write the failing tests**

Append to `payments/test_coverage.py`:

```python
# ---- bill / un-bill ---------------------------------------------------------

def test_billing_requotes_a_paid_registration(period, student):
    reg = _reg(student, _tier(_event("bill-me"), amount="200.00"))
    changed = coverage.bill_skipped_coverage(student, period)
    assert changed == [reg]
    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("200.00")
    assert reg.status == Registration.Status.AWAITING_PAYMENT
    assert reg.quoted_explanation == coverage.REBILLED_EXPLANATION
    assert reg.needs_payment is True      # the "Pay →" button renders
    assert "Re-billed $200.00" in reg.staff_notes


def test_billing_leaves_a_pending_approval_row_pending(period, student):
    """approve() routes on the amount, so the row must keep its status or it
    would skip the faculty approval it is waiting for."""
    reg = _reg(student, _tier(_event("await-approval"), amount="150.00"),
               status=Registration.Status.PENDING_APPROVAL)
    coverage.bill_skipped_coverage(student, period)
    reg.refresh_from_db()
    assert reg.status == Registration.Status.PENDING_APPROVAL
    assert reg.quoted_amount == Decimal("150.00")


def test_billing_is_idempotent(period, student):
    reg = _reg(student, _tier(_event("twice"), amount="200.00"))
    coverage.bill_skipped_coverage(student, period)
    assert coverage.bill_skipped_coverage(student, period) == []
    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("200.00")


def test_unbilling_restores_coverage(period, student):
    reg = _reg(student, _tier(_event("restore"), amount="200.00"))
    coverage.bill_skipped_coverage(student, period)
    changed = coverage.unbill_skipped_coverage(student, period)
    assert [r.pk for r in changed] == [reg.pk]
    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("0")
    assert reg.status == Registration.Status.PAID    # access gate passes again
    assert reg.quoted_explanation == coverage.COVERED_EXPLANATION


def test_unbilling_leaves_a_paid_fee_alone(period, student):
    """If they paid the re-billed fee and then commit to tuition, that is a
    refund conversation for the treasurer, not a silent unwind."""
    reg = _reg(student, _tier(_event("already-paid"), amount="200.00"))
    coverage.bill_skipped_coverage(student, period)
    Registration.objects.filter(pk=reg.pk).update(status=Registration.Status.PAID)
    assert coverage.unbill_skipped_coverage(student, period) == []
    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("200.00")


def test_unbilling_ignores_another_academic_year(period, student):
    reg = _reg(student, _tier(_event("other-yr", start=date(2025, 10, 1)),
                             amount="200.00"))
    Registration.objects.filter(pk=reg.pk).update(
        quoted_amount=Decimal("200.00"),
        quoted_explanation=coverage.REBILLED_EXPLANATION,
        status=Registration.Status.AWAITING_PAYMENT,
    )
    assert coverage.unbill_skipped_coverage(student, period) == []


def test_a_free_covered_tier_owes_nothing(period, student):
    _reg(student, _tier(_event("free-tier"), amount="0.00"))
    assert coverage.bill_skipped_coverage(student, period) == []
```

- [ ] **Step 2: Run them**

Run: `uv run pytest payments/test_coverage.py -q -p no:randomly`
Expected: all PASS — Task 1 already wrote the implementation. If one fails, the bug is in `payments/coverage.py`, not in the test: fix the module.

`test_unbilling_leaves_a_paid_fee_alone` and `test_unbilling_ignores_another_academic_year` use `.update()` deliberately, to set state without re-running `save()` side effects.

- [ ] **Step 3: Commit**

```bash
git add payments/test_coverage.py
git commit -m "test(payments): pin bill/un-bill rules for skipped coverage (#485)"
```

---

### Task 3: The decision view — warn, then bill

**Files:**
- Modify: `payments/views.py` (`tuition_decision`, at line 2339)
- Create: `payments/templates/payments/skip_confirm.html`
- Test: `payments/test_tuition.py` (append after `test_post_updates_existing_enrollment`, which ends at line 223)

**Interfaces:**
- Consumes: `coverage.covered_registrations(user, period)`, `coverage.bill_skipped_coverage(user, period)`, `coverage.unbill_skipped_coverage(user, period)`, `coverage.retro_amount(tier)`.
- Produces: the POST contract `confirm=1` on `/tuition/`. Task 4 hangs a notification off the billing branch.

- [ ] **Step 1: Write the failing tests**

Append to `payments/test_tuition.py`. They reuse that file's `current_period` fixture and `_mk_candidate()` helper.

```python
# --- Skipping after consuming coverage (task #485) -----------------------


def _covered_registration(user, period, amount="200.00"):
    """A $0 registration that tuition coverage paid for, inside `period`."""
    from datetime import timedelta

    from events.models import Audience, Event, PriceTier
    from payments import coverage
    from registrations.models import Registration

    when = period.start_date + timedelta(days=30)
    event = Event.objects.create(
        title="Covered Seminar", slug=f"covered-{user.pk}",
        start_date=when, end_date=when,
        status=Event.Status.OPEN, published=True,
    )
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal(amount),
        covered_by_tuition=True,
    )
    return Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("0"),
        quoted_explanation=coverage.COVERED_EXPLANATION,
        status=Registration.Status.PAID,
    )


@pytest.mark.django_db
def test_skipping_with_coverage_consumed_asks_to_confirm_first(client, current_period):
    """The first POST warns and records nothing — the member sees what skipping
    will cost before it happens."""
    from registrations.models import Registration

    u = _mk_candidate()
    TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.COMMITTED,
    )
    reg = _covered_registration(u, current_period)
    client.force_login(u)
    resp = client.post(reverse("tuition"), {"status": "skipping"})

    assert resp.status_code == 200                  # the confirm page, not a redirect
    assert b"Covered Seminar" in resp.content
    assert b"200.00" in resp.content
    enr = TuitionEnrollment.objects.get(user=u, tuition_period=current_period)
    assert enr.status == TuitionEnrollment.Status.COMMITTED   # unchanged
    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("0")                  # unbilled


@pytest.mark.django_db
def test_confirmed_skipping_bills_the_covered_registrations(client, current_period):
    from registrations.models import Registration

    u = _mk_candidate()
    TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.COMMITTED,
    )
    reg = _covered_registration(u, current_period)
    client.force_login(u)
    resp = client.post(reverse("tuition"), {"status": "skipping", "confirm": "1"})

    assert resp.status_code == 302
    enr = TuitionEnrollment.objects.get(user=u, tuition_period=current_period)
    assert enr.status == TuitionEnrollment.Status.SKIPPING
    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("200.00")
    assert reg.status == Registration.Status.AWAITING_PAYMENT


@pytest.mark.django_db
def test_skipping_with_no_coverage_consumed_records_in_one_post(client, current_period):
    u = _mk_candidate()
    client.force_login(u)
    resp = client.post(reverse("tuition"), {"status": "skipping"})
    assert resp.status_code == 302
    enr = TuitionEnrollment.objects.get(user=u, tuition_period=current_period)
    assert enr.status == TuitionEnrollment.Status.SKIPPING


@pytest.mark.django_db
def test_committing_after_skipping_unbills_and_restores_access(client, current_period):
    """The member's route back: commit to pay and the events are covered again,
    without any money moving."""
    from registrations.models import Registration

    u = _mk_candidate()
    TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.COMMITTED,
    )
    reg = _covered_registration(u, current_period)
    client.force_login(u)
    client.post(reverse("tuition"), {"status": "skipping", "confirm": "1"})
    client.post(reverse("tuition"), {"status": "committed"})

    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("0")
    assert reg.status == Registration.Status.PAID
    enr = TuitionEnrollment.objects.get(user=u, tuition_period=current_period)
    assert enr.status == TuitionEnrollment.Status.COMMITTED
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest payments/test_tuition.py -k "skipping or committing_after" -q -p no:randomly`
Expected: the confirm test FAILs (`assert 302 == 200` — today the first POST records immediately) and the billing tests FAIL on the amount still being `0`.

- [ ] **Step 3: Write the confirm template**

Create `payments/templates/payments/skip_confirm.html`. Copy follows the commas-not-em-dashes rule and the `event_edit_confirm.html` shape.

```html
{% extends "core/base.html" %}
{% block title %}Skipping tuition · LSP{% endblock %}
{% block content %}
<div class="max-w-2xl mx-auto space-y-6">

  <header class="space-y-1">
    <h1 class="font-serif text-3xl text-base-content">Before you skip {{ period.name }}</h1>
    <p class="text-sm text-base-content/70">
      Your tuition covered the events below. If you skip tuition for
      {{ period.name }}, the regular fee applies to each of them.
    </p>
  </header>

  <div class="rounded-xl border border-base-300/60 bg-base-100 p-4 space-y-3">
    <table class="table table-sm">
      <thead><tr><th>Event</th><th class="text-right">Fee</th></tr></thead>
      <tbody>
        {% for row in rows %}
        <tr>
          <td>{{ row.registration.event.title }}</td>
          <td class="text-right whitespace-nowrap">${{ row.amount }}</td>
        </tr>
        {% endfor %}
      </tbody>
      <tfoot>
        <tr><th>Total</th><th class="text-right whitespace-nowrap">${{ total }}</th></tr>
      </tfoot>
    </table>
    <p class="text-xs text-base-content/60">
      You'll be able to pay each fee from your registration page. If you decide
      to pay tuition after all, record that on your Account tab and these events
      go back to being covered, at no cost.
    </p>
  </div>

  <div class="flex flex-wrap gap-3">
    <form method="post" action="{% url 'tuition' %}">
      {% csrf_token %}
      <input type="hidden" name="status" value="skipping">
      <input type="hidden" name="confirm" value="1">
      {% if period_slug %}<input type="hidden" name="period" value="{{ period_slug }}">{% endif %}
      <button type="submit" class="btn btn-warning">Skip tuition and accept the fees</button>
    </form>
    <a href="{{ account_url }}" class="btn btn-ghost">Cancel</a>
  </div>

</div>
{% endblock %}
```

- [ ] **Step 4: Wire the view**

In `payments/views.py`, replace the body of `tuition_decision` (from `if request.method == "POST"` through the final `return redirect(_account_tab_url())`, lines 2350-2393) with:

```python
    if request.method == "POST" and profile.owes_tuition and period is not None:
        form = TuitionDecisionForm(request.POST)
        if form.is_valid():
            status = form.cleaned_data["status"]
            # Skipping a year whose events tuition already covered re-bills
            # those events (task #485). Warn first: the member sees the cost,
            # confirms, and only then is anything recorded or billed.
            if status == "skipping" and not request.POST.get("confirm"):
                rows = [
                    {"registration": r, "amount": coverage.retro_amount(r.price_tier)}
                    for r in coverage.covered_registrations(request.user, period)
                ]
                rows = [r for r in rows if r["amount"] > 0]
                if rows:
                    return render(request, "payments/skip_confirm.html", {
                        "period": period,
                        "period_slug": request.POST.get("period", ""),
                        "rows": rows,
                        "total": sum(r["amount"] for r in rows),
                        "account_url": _account_tab_url(),
                    })
            with transaction.atomic():
                if status == "payment_plan":
                    # Applying for a payment plan is a request to the Board,
                    # not a self-serve status (task #450 phase B) — the
                    # enrollment records PLAN_REQUESTED (not PAYMENT_PLAN;
                    # that's reached only once the Board approves) and a
                    # PENDING TuitionPlanApplication carries the reasons for
                    # their review.
                    TuitionEnrollment.objects.update_or_create(
                        user=request.user, tuition_period=period,
                        defaults={
                            "status": TuitionEnrollment.Status.PLAN_REQUESTED,
                        },
                    )
                    application, created = (
                        TuitionPlanApplication.objects.get_or_create(
                            user=request.user, tuition_period=period,
                            status=TuitionPlanApplication.Status.PENDING,
                            defaults={
                                "reasons": form.cleaned_data["reasons"],
                            },
                        )
                    )
                    if not created:
                        # Re-submitting while still pending updates the
                        # reasons in place rather than erroring or stacking
                        # duplicate rows (the partial unique constraint only
                        # allows one PENDING application per user/period).
                        application.reasons = form.cleaned_data["reasons"]
                        application.save(update_fields=["reasons"])
                    notify_plan_application_submitted(application)
                else:
                    TuitionEnrollment.objects.update_or_create(
                        user=request.user, tuition_period=period,
                        defaults={"status": status},
                    )
                # Bill or restore the events tuition coverage paid for. A
                # paying decision (committed / plan request) restores coverage,
                # so committing returns their access without money moving.
                if status == "skipping":
                    billed = coverage.bill_skipped_coverage(request.user, period)
                else:
                    billed = []
                    coverage.unbill_skipped_coverage(request.user, period)
            if billed:
                notify_coverage_rebilled(request.user, period, billed)
            messages.success(request, "Your tuition decision has been recorded.")
        else:
            messages.error(request, "Please choose one of the listed options.")
    return redirect(_account_tab_url())
```

Add the imports at the top of `payments/views.py` alongside the existing ones: `from . import coverage` in the local-app group, and `notify_coverage_rebilled` onto the existing `from .notifications import (...)` list.

- [ ] **Step 5: Add the notification the branch above calls**

The billing branch calls `notify_coverage_rebilled`, so it belongs to this task's deliverable, not a later one. Add it to `payments/notifications.py` after `notify_plan_application_decided`:

```python
def notify_coverage_rebilled(user, period, registrations) -> None:
    """Tell the member the events tuition had covered now carry their regular
    fee, because they recorded skipping for the year (task #485)."""
    total = sum(r.quoted_amount for r in registrations)
    count = len(registrations)
    plural = "registration" if count == 1 else "registrations"
    notify(
        user, Category.ACCOUNT_UPDATES,
        title=(
            f"{count} {plural} now carries the regular fee, ${total} in total, "
            f"because you're skipping tuition for {period.name}."
        ),
        body=(
            "You can pay each fee from its registration page. If you decide to "
            f"pay tuition for {period.name} after all, record that on your "
            "Account tab and these events go back to being covered, at no cost."
        ),
        url=_account_tab_url(),
    )
```

- [ ] **Step 6: Run the view tests**

Run: `uv run pytest payments/test_tuition.py -q -p no:randomly`
Expected: all PASS, including the pre-existing decision-view tests (`test_post_committed_creates_enrollment`, `test_post_updates_existing_enrollment`) — the plan-request branch is unchanged.

- [ ] **Step 7: Commit**

```bash
git add payments/views.py payments/notifications.py payments/templates/payments/skip_confirm.html payments/test_tuition.py
git commit -m "feat(payments): warn then re-bill covered events when a year is skipped (#485)"
```

---

### Task 4: The two copy fixes, and a test for the notification

**Files:**
- Modify: `payments/notifications.py` (rewrite the decline body added in #484, lines 217-241)
- Modify: `registrations/templates/registrations/register_confirm.html:62-69`
- Modify: `registrations/views.py::registration_confirm` (line 238 — a two-key context dict)
- Test: `payments/test_plan_review_queue.py:180-200` (the decline test), `payments/test_coverage.py` (append)

**Interfaces:**
- Consumes: `coverage.REBILLED_EXPLANATION`, and `notify_coverage_rebilled(user, period, registrations) -> None` written in Task 3.
- Produces: `rebilled_explanation` in the confirmation page's template context.

- [ ] **Step 1: Write the failing tests**

Append to `payments/test_coverage.py`:

```python
# ---- notification ----------------------------------------------------------

def test_rebill_notification_names_the_count_and_total(period, student):
    from notifications.categories import Category
    from notifications.models import Notification
    from payments.notifications import notify_coverage_rebilled

    reg = _reg(student, _tier(_event("notify-me"), amount="200.00"))
    coverage.bill_skipped_coverage(student, period)
    notify_coverage_rebilled(student, period, [reg])

    note = Notification.objects.get(
        recipient=student, category=Category.ACCOUNT_UPDATES,
    )
    assert "1 registration" in note.title
    assert "200.00" in note.title or "200.00" in note.body
```

And in `payments/test_plan_review_queue.py`, replace the two assertions added in #484 (`assert "tuition coverage" in note.body` / `assert "settling" in note.body`) with the concrete consequence:

```python
    # A declined plan leaves them with a choice, and the consequence of each
    # branch is stated (task #485).
    assert "regular fee" in note.body
    assert "covered" in note.body
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest payments/test_coverage.py::test_rebill_notification_names_the_count_and_total payments/test_plan_review_queue.py::test_decline_deletes_enrollment_and_notifies -q -p no:randomly`
Expected: the notification test PASSES (Task 3 wrote the function; this pins its wording), and the decline test FAILS on `"regular fee" in note.body`.

- [ ] **Step 3: Rewrite the decline body**

In `payments/notifications.py::notify_plan_application_decided`, replace the `body = (...)` assignment added by #484 with:

```python
        # A pending request carried event coverage (task #484). Say what each
        # branch of the choice now costs (task #485).
        body = (
            "Your tuition decision is open again on your Account tab. If you "
            "record that you plan to pay tuition, any events you registered "
            "for stay covered. If you skip this year, those events carry their "
            "regular fee and you'll be shown the total before it applies."
        )
```

- [ ] **Step 4: Run those tests**

Run: `uv run pytest payments/test_coverage.py payments/test_plan_review_queue.py -q -p no:randomly`
Expected: all PASS.

- [ ] **Step 5: Explain the re-billed registration on its own page**

In `registrations/templates/registrations/register_confirm.html`, the unpaid branch at lines 62-69 currently reads:

```html
  {% elif registration.needs_payment %}
  <div role="alert" class="alert alert-warning">
    <span>{% if registration.decided_at %}Your registration was approved — complete payment to confirm your place.{% else %}Your place isn't confirmed until payment is complete.{% endif %}</span>
  </div>
```

Add a re-billed case ahead of the generic wording, so "Awaiting payment" always states its cause:

```html
  {% elif registration.needs_payment %}
  <div role="alert" class="alert alert-warning">
    <span>{% if registration.quoted_explanation == rebilled_explanation %}Your tuition covered this event until you recorded that you're skipping tuition for the year, so the regular fee now applies. Recording that you plan to pay tuition on your Account tab restores the coverage.{% elif registration.decided_at %}Your registration was approved — complete payment to confirm your place.{% else %}Your place isn't confirmed until payment is complete.{% endif %}</span>
  </div>
```

The template needs `rebilled_explanation` in its context. `registration_confirm` (`registrations/views.py:238`) currently renders `{"registration": reg}`; make it:

```python
@login_required
def registration_confirm(request, reg_id: int):
    reg = get_object_or_404(Registration, pk=reg_id, user=request.user)
    return render(
        request,
        "registrations/register_confirm.html",
        {
            "registration": reg,
            # Lets the page say *why* a formerly covered place now wants money
            # (task #485) without duplicating the marker string in a template.
            "rebilled_explanation": coverage.REBILLED_EXPLANATION,
        },
    )
```

with `from payments import coverage` added to the imports at the top of `registrations/views.py`. Keep the existing `@login_required` decorator that precedes the function.

- [ ] **Step 6: Test that copy**

Append to `payments/test_coverage.py`:

```python
def test_confirmation_page_explains_a_rebilled_registration(client, period, student):
    reg = _reg(student, _tier(_event("explain-me"), amount="200.00"))
    coverage.bill_skipped_coverage(student, period)
    client.force_login(student)
    body = client.get(
        reverse("registrations:confirm", args=[reg.pk])
    ).content.decode()
    assert "skipping tuition for the year" in body
    assert "restores the coverage" in body
```

Add `from django.urls import reverse` to that file's imports if it is not already there.

Run: `uv run pytest payments/test_coverage.py -q -p no:randomly`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add payments/notifications.py payments/test_plan_review_queue.py payments/test_coverage.py registrations/views.py registrations/templates/registrations/register_confirm.html
git commit -m "feat(payments): tell the member what skipping cost, and why (#485)"
```

---

### Task 5: Docs — the treasurer guide and the CLAUDE.md entry

**Files:**
- Modify: `core/docs/treasurer-guide.md` (the "Tuition & registration gate" section rewritten by #484)
- Modify: `CLAUDE.md` (append after the task #484 entry)

**Interfaces:**
- Consumes: the finished behavior from Tasks 1-4.
- Produces: nothing.

- [ ] **Step 1: Add a guide section**

In `core/docs/treasurer-guide.md`, immediately after the "Full case table" block and before the `**Non-in-training roles**` paragraph that closes the section, insert:

```markdown
### Skipping a year whose events tuition already covered

Coverage is provisional in one direction: a member can register for a covered
event and *later* record that they're skipping tuition for the year (or have a
payment-plan application declined and then choose to skip). When they record
skipping, the site shows them every event tuition covered that year with its
regular fee and a total, and on confirmation **re-bills each one**: the
registration moves to Awaiting payment at the regular fee, which turns on its
"Pay" button and the ordinary registration reminders. They lose event access
until it's settled.

The reverse also holds. If they later record that they plan to pay tuition, or
apply for a plan, those registrations go straight back to covered at $0 and
access returns, with no money moving. A fee they already **paid** is never
unwound automatically, that's a refund for you to decide on.

**This only fires on the member's own confirmed action.** Setting someone's
tuition status yourself, in the Django admin or from the Accounts tab, does not
re-bill anything, and neither do the import or backfill commands. If a member's
year should be re-billed and they haven't done it themselves, adjust the
registration amount, or add a charge on their account page.
```

Watch the rendered-markdown gotcha: no continuation line inside a list item may start with `+`, `-`, or `*`.

- [ ] **Step 2: Verify the guide renders**

Run: `uv run pytest content/test_guides.py -q -p no:randomly`
Expected: PASS (`test_all_listed_guides_render` is the one that exercises `render_doc`).

- [ ] **Step 3: Add the CLAUDE.md entry**

Append immediately after the task #484 bullet ("**A requested payment plan covers events** (task #484)…"), before the "Milestones 7–8 then cover…" paragraph. Unspaced em dashes here.

```markdown
- **Skipping a covered year re-bills the events** (task #485, follow-on to
  #484). #484 made coverage provisional in one direction, and nothing owned the
  other: a member who consumed coverage and then ended up SKIPPING owed nothing
  for those events, because a covered registration is created with
  `quoted_amount=0` and **no Payment and no Charge** (`mint_registration_charge`
  requires a positive amount), while SKIPPING is exempt from tuition charges.
  The Board declining a plan is only the rarest route in — the likelier one is a
  member who records COMMITTED, registers free, then re-records SKIPPING — so
  the mechanism keys off the *decision*, not the decline. New
  `payments/coverage.py` answers what coverage bought in a year
  (`covered_registrations`, which excludes comps and pricing-code freebies since
  neither is coverage), what it was worth (`retro_amount` — the tier's
  `base_amount`, or `minimum_amount` for a sliding tier, since a skipping member
  would have picked their own figure at or above the floor), and bills or
  un-bills it. **Billing re-quotes the Registration rather than minting a
  Charge**: `quoted_amount` + AWAITING_PAYMENT lights up the built "Pay →"
  Stripe button, the registration reminders, and `mint_registration_charge` at
  settle, where a bare Charge would have been unpayable — the member-facing
  payment endpoints are dues, tuition-in-full, installments, donations, and
  per-registration checkout, nothing else. A PENDING_APPROVAL row gets its
  amount rewritten but **keeps its status**, because `approve()` routes on the
  amount and flipping it would skip the faculty approval it awaits. Recording a
  paying decision un-bills, so **committing to pay restores event access without
  any money moving**; a fee actually paid is never unwound (treasurer's refund
  call). The member confirms on an interstitial listing every event, its fee, and
  the total before anything is recorded, and gets one notification after. Access
  loss while re-billed is accepted, deliberately: the routes back are the
  registration's Pay button and the tuition decision form. **Staff paths do not
  auto-bill** — admin, the treasurer's set-status, `backfill_tuition_status`, the
  importers — or a historical backfill would retro-bill years of events. No
  migration: the marker is the `quoted_explanation` string, held in
  `coverage.REBILLED_EXPLANATION` and pinned by a test, mirroring how
  `"Covered by tuition (tuition-paying member, REG-4)"` already identifies a
  covered registration. Design:
  `docs/superpowers/specs/2026-07-29-skipped-coverage-rebilling-design.md`.
```

- [ ] **Step 4: Run the full suite and the linter**

Run: `uv run pytest -q`
Expected: PASS, zero failures.

Run: `uv run ruff check .`
Expected: `All checks passed!`

If a failure appears in a suite this plan never touched, read it rather than editing the assertion to fit — a covered registration changing shape can legitimately break a registration or ledger test, and the test may be right.

- [ ] **Step 5: Commit**

```bash
git add core/docs/treasurer-guide.md CLAUDE.md
git commit -m "docs: re-billing a skipped covered year (#485)"
```

---

## Verification

Walk the four states rather than one happy path:

1. **Skip with coverage consumed** → confirm page lists events and total, records nothing; confirming re-bills each to AWAITING_PAYMENT and notifies.
2. **Skip then commit** → back to $0/PAID, access restored, no payment involved.
3. **Skip, pay the fee, then commit** → the paid registration is untouched.
4. **Skip with nothing consumed** → one POST, no interstitial, no charges.

Then the exclusions, which are where a bug would hide: a comp, a pricing-code freebie, a registration in another academic year, and a `PENDING_APPROVAL` row (amount rewritten, status held).

No prod data step: nothing is migrated or backfilled, and no existing registration changes until a member records a decision. Deploy is the ordinary push-to-`main` path; `pushed-is-not-deployed` applies, so watch the Deploy run go green.
