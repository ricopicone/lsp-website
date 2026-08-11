# Applying tuition coverage to existing registrations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recording a covering tuition decision prices that year's already-created unpaid registrations at $0, on both the member and treasurer paths.

**Architecture:** Replace `coverage.unbill_skipped_coverage` — which matches only the task #485 re-bill marker string — with `coverage.apply_coverage`, one structural predicate that asks what coverage owes the member now. Wire it into `tuition_decision` (with a notification) and `treasurer_tuition_set_status` (silent).

**Tech Stack:** Django 5.2, pytest-django, Stripe Checkout.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-11-apply-coverage-to-existing-registrations-design.md`.
- Member-facing copy uses **commas, not em dashes** (site-copy exception to the house style), and says *what*, not *why*.
- A registration with money actually on it is never unwound — status filter excludes it.
- `PENDING_APPROVAL` keeps its status: `approve()` routes on the amount.
- The treasurer path never re-bills on skipping (#485's staff-paths rule stands).
- No migration, no backfill, no feature flag.
- Run `uv run pytest` and `uv run ruff check .` before committing.

---

### Task 1: `apply_coverage` replaces `unbill_skipped_coverage`

**Files:**
- Modify: `payments/coverage.py:26-31` (constant comment), `payments/coverage.py:107-149` (replace function)
- Test: `payments/test_coverage.py`

**Interfaces:**
- Produces: `coverage.apply_coverage(user, period) -> list[Registration]` — the rows changed. Returns `[]` when `period is None`, when the user has no `TuitionEnrollment` for `period`, or when that enrollment's `covers_seminars` is False.
- Consumes: `stripe_sync.expire_open_sessions(registration, *, reason: str) -> int`, `ledger.period_for_event(event) -> TuitionPeriod | None`.

- [ ] **Step 1: Extend the test helper to take an explanation, and add a covering-enrollment fixture**

In `payments/test_coverage.py`, add the import and fixture, and give `_reg` an `explanation` argument:

```python
from payments.models import TuitionEnrollment, TuitionPeriod


@pytest.fixture
def committed(period, student):
    """A covering decision for the year — what makes coverage apply."""
    return TuitionEnrollment.objects.create(
        user=student, tuition_period=period,
        status=TuitionEnrollment.Status.COMMITTED,
    )


def _reg(student, tier, *, status=Registration.Status.PAID, amount="0.00",
         code=None, explanation=None):
    return Registration.objects.create(
        user=student, event=tier.event, price_tier=tier, pricing_code=code,
        quoted_amount=Decimal(amount),
        quoted_explanation=(
            coverage.COVERED_EXPLANATION if explanation is None else explanation
        ),
        status=status,
    )
```

- [ ] **Step 2: Write the failing tests**

Replace the three `unbill_skipped_coverage` tests (`test_unbilling_restores_coverage`, `test_unbilling_leaves_a_paid_fee_alone`, `test_unbilling_ignores_another_academic_year`) with these, keeping the `# ---- bill / un-bill ----` section header:

```python
def _quoted(student, slug, amount="200.00", start=date(2026, 10, 1)):
    """A registration quoted the regular fee — what task #561 is about. It
    carries no re-bill marker, because nothing ever re-billed it: it was
    created before a covering decision existed."""
    return _reg(
        student, _tier(_event(slug, start=start), amount=amount),
        status=Registration.Status.AWAITING_PAYMENT, amount=amount,
        explanation="Standard All price.",
    )


def test_apply_coverage_restores_a_row_that_was_never_rebilled(
    period, student, committed,
):
    """Task #561: registered before the decision existed, so it was quoted the
    regular fee and carries no marker for unbilling to match."""
    reg = _quoted(student, "quoted-early")
    changed = coverage.apply_coverage(student, period)
    assert [r.pk for r in changed] == [reg.pk]
    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("0")
    assert reg.status == Registration.Status.PAID
    assert reg.quoted_explanation == coverage.COVERED_EXPLANATION
    assert reg.needs_payment is False
    assert "Covered by tuition" in reg.staff_notes


def test_apply_coverage_restores_a_rebilled_row(period, student, committed):
    """The task #485 round trip still works — a re-billed row is a strict
    subset of what the predicate selects."""
    reg = _reg(student, _tier(_event("restore"), amount="200.00"))
    coverage.bill_skipped_coverage(student, period)
    changed = coverage.apply_coverage(student, period)
    assert [r.pk for r in changed] == [reg.pk]
    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("0")
    assert reg.status == Registration.Status.PAID


def test_apply_coverage_needs_a_covering_enrollment(period, student):
    """No decision on file covers nothing."""
    _quoted(student, "no-decision")
    assert coverage.apply_coverage(student, period) == []


def test_apply_coverage_ignores_a_skipping_year(period, student):
    TuitionEnrollment.objects.create(
        user=student, tuition_period=period,
        status=TuitionEnrollment.Status.SKIPPING,
    )
    _quoted(student, "skipped-year")
    assert coverage.apply_coverage(student, period) == []


def test_apply_coverage_leaves_a_pending_approval_row_pending(
    period, student, committed,
):
    """approve() routes on the amount, so the row must keep its status."""
    reg = _reg(student, _tier(_event("await-ok"), amount="150.00"),
               status=Registration.Status.PENDING_APPROVAL, amount="150.00",
               explanation="Standard All price.")
    coverage.apply_coverage(student, period)
    reg.refresh_from_db()
    assert reg.status == Registration.Status.PENDING_APPROVAL
    assert reg.quoted_amount == Decimal("0")


def test_apply_coverage_leaves_a_paid_fee_alone(period, student, committed):
    """A fee genuinely paid is a refund conversation for the treasurer."""
    reg = _reg(student, _tier(_event("already-paid"), amount="200.00"),
               status=Registration.Status.PAID, amount="200.00",
               explanation="Standard All price.")
    assert coverage.apply_coverage(student, period) == []
    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("200.00")


def test_apply_coverage_ignores_a_pricing_code_row(period, student, committed):
    """A discounted place is the code's doing, not tuition's."""
    from events.models import PricingCode

    tier = _tier(_event("coded"), amount="200.00")
    code = PricingCode.objects.create(
        event=tier.event, code="HALF-1", issued_by=student,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("50"),
    )
    _reg(student, tier, status=Registration.Status.AWAITING_PAYMENT,
         amount="100.00", code=code, explanation="50% off via code HALF-1.")
    assert coverage.apply_coverage(student, period) == []


def test_apply_coverage_ignores_another_academic_year(period, student, committed):
    _quoted(student, "other-yr", start=date(2025, 10, 1))
    assert coverage.apply_coverage(student, period) == []


def test_apply_coverage_expires_a_live_checkout_session(
    period, student, committed, monkeypatch,
):
    """A member returning to a stale tab would otherwise pay for a place they
    now hold for free, and complete_payment mints no Charge against it."""
    from payments.models import Payment

    reg = _quoted(student, "stale-tab", amount="500.00")
    payment = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, user=student, registration=reg,
        amount=Decimal("500.00"), method=Payment.Method.STRIPE,
        status=Payment.Status.PENDING,
        stripe_checkout_session_id="cs_test_561",
    )
    expired = []
    monkeypatch.setattr("stripe.checkout.Session.expire", expired.append)

    coverage.apply_coverage(student, period)

    assert expired == ["cs_test_561"]
    payment.refresh_from_db()
    assert payment.status == Payment.Status.ABANDONED
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest payments/test_coverage.py -q`
Expected: FAIL with `AttributeError: module 'payments.coverage' has no attribute 'apply_coverage'`.

- [ ] **Step 4: Implement**

In `payments/coverage.py`, update the `REBILLED_EXPLANATION` comment (nothing reads it back now):

```python
#: The explanation a re-billed registration carries. Nothing matches on it —
#: ``apply_coverage`` asks the structural question instead (task #561) — but it
#: is what the member and the treasurer read on the row, and a test pins it.
```

Then replace `unbill_skipped_coverage` entirely with:

```python
def apply_coverage(user, period) -> list:
    """Price every unpaid registration ``period``'s tuition covers at $0.

    Called wherever a covering decision is recorded, by the member or by the
    treasurer. It answers "what does coverage owe this member now" rather than
    undoing a specific earlier action, so it reaches both the row
    ``bill_skipped_coverage`` re-billed and the row quoted the regular fee
    because it was created before any covering decision existed (task #561).
    Those two differ only in a string; matching that string is what left the
    second case unfixable.

    A row with money actually on it is excluded by the status filter: a fee
    genuinely paid is a refund conversation for the treasurer, never a silent
    unwind. Returns the rows changed.
    """
    from payments.ledger import period_for_event
    from payments.models import TuitionEnrollment
    from payments.stripe_sync import expire_open_sessions
    from registrations.models import Registration

    if period is None:
        return []
    # Guarded once rather than per row: the row filter already pins every
    # candidate to ``period``, so this is ``is_tuition_current`` for all of
    # them in a single query.
    enrollment = TuitionEnrollment.objects.filter(
        user=user, tuition_period=period,
    ).first()
    if not (enrollment and enrollment.covers_seminars):
        return []

    today = timezone.now().date()
    changed = []
    rows = (
        Registration.objects
        .filter(
            user=user,
            price_tier__covered_by_tuition=True,
            pricing_code__isnull=True,
            quoted_amount__gt=Decimal("0"),
            status__in=(
                Registration.Status.AWAITING_PAYMENT,
                Registration.Status.PENDING_APPROVAL,
            ),
        )
        .select_related("event", "price_tier")
        .order_by("event__start_date", "pk")
    )
    for reg in rows:
        if period_for_event(reg.event) != period:
            continue
        # Kill any live Checkout session first. Otherwise a member returning to
        # a stale tab pays for a place they now hold for free, and
        # ``complete_payment``'s settle guard mints no Charge against it, so the
        # money lands as unattributed credit for the treasurer to refund by hand.
        expire_open_sessions(
            reg, reason="Tuition coverage applied — no payment is owed.",
        )
        reg.quoted_amount = Decimal("0")
        reg.quoted_explanation = COVERED_EXPLANATION
        # approve() routes a PENDING_APPROVAL row on the amount, so flipping it
        # here would skip the faculty approval it is waiting for.
        if reg.status == Registration.Status.AWAITING_PAYMENT:
            reg.status = Registration.Status.PAID
        reg.staff_notes = (
            f"{reg.staff_notes}\n[{today}] Covered by tuition for "
            f"{period.name}: a paying decision is on file, so no payment is "
            "owed (task #561)."
        ).strip()
        reg.save(update_fields=(
            "quoted_amount", "quoted_explanation", "status", "staff_notes",
        ))
        changed.append(reg)
    return changed
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest payments/test_coverage.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add payments/coverage.py payments/test_coverage.py
git commit -m "feat(payments): apply tuition coverage by predicate, not marker (task #561)"
```

---

### Task 2: The restore notification

**Files:**
- Modify: `payments/notifications.py:295-313` (add after `notify_coverage_rebilled`)
- Test: `payments/test_coverage.py`

**Interfaces:**
- Produces: `notify_coverage_restored(user, period, registrations) -> None`.

- [ ] **Step 1: Write the failing test**

Add to `payments/test_coverage.py` under the `# ---- notification ----` section:

```python
def test_restore_notification_names_the_count(period, student, committed):
    from notifications.models import Notification
    from payments.notifications import notify_coverage_restored

    _quoted(student, "notify-restore")
    restored = coverage.apply_coverage(student, period)
    notify_coverage_restored(student, period, restored)

    note = Notification.objects.filter(user=student).latest("created_at")
    assert "1 registration" in note.title
    assert period.name in note.title
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest payments/test_coverage.py::test_restore_notification_names_the_count -q`
Expected: FAIL with `ImportError: cannot import name 'notify_coverage_restored'`.

- [ ] **Step 3: Implement**

In `payments/notifications.py`, directly after `notify_coverage_rebilled`:

```python
def notify_coverage_restored(user, period, registrations) -> None:
    """Tell the member the events they were quoted a fee for are covered by
    their tuition after all (task #561)."""
    count = len(registrations)
    plural = "registration" if count == 1 else "registrations"
    notify(
        user, Category.ACCOUNT_UPDATES,
        title=(
            f"{count} {plural} now covered by your {period.name} tuition, "
            "at no cost."
        ),
        body=(
            "Your tuition covers these events, so there is nothing to pay. "
            "If you had started a payment for any of them, it was cancelled "
            "and you were not charged."
        ),
        url=_account_tab_url(),
    )
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest payments/test_coverage.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add payments/notifications.py payments/test_coverage.py
git commit -m "feat(payments): notify a member when coverage is restored (task #561)"
```

---

### Task 3: Wire both views

**Files:**
- Modify: `payments/views.py:43` (import), `payments/views.py:2416-2428` (`tuition_decision`), `payments/views.py:1805-1815` (`treasurer_tuition_set_status`)
- Test: `payments/test_coverage.py`

**Interfaces:**
- Consumes: `coverage.apply_coverage`, `notify_coverage_restored`.

- [ ] **Step 1: Write the failing tests**

Add to `payments/test_coverage.py`:

```python
# ---- view wiring -----------------------------------------------------------

@pytest.fixture
def staff_user(db):
    """Mirrors the fixture in payments/test_tuition.py:447."""
    u = User.objects.create_user(email="cov-staff@x.test", password="x")
    u.is_staff = True
    u.save()
    return u


def test_member_decision_applies_coverage_and_notifies(period, student, client):
    """Recording a paying decision covers the events already registered for."""
    from notifications.models import Notification

    reg = _quoted(student, "member-path")
    client.force_login(student)
    # URL names are unnamespaced (config/urls.py:163); the decision form posts
    # the period slug, and _resolve_tuition_period accepts current or upcoming.
    client.post(reverse("tuition"),
                {"status": "committed", "period": period.slug})

    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("0")
    assert reg.status == Registration.Status.PAID
    assert Notification.objects.filter(
        user=student, title__contains="now covered by your").exists()


def test_treasurer_set_status_applies_coverage_silently(
    period, student, client, staff_user,
):
    """The treasurer flips historical years in cleanup, so no member mail."""
    from notifications.models import Notification

    reg = _quoted(student, "treasurer-path")
    client.force_login(staff_user)
    client.post(
        reverse("treasurer_tuition_set_status", args=[student.pk]),
        {"status": "committed", "period": period.pk},
    )

    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("0")
    assert reg.status == Registration.Status.PAID
    assert not Notification.objects.filter(
        user=student, title__contains="now covered by your").exists()
```

The member-path test needs `student.profile` to satisfy `tuition_decision`'s
`profile.owes_tuition` guard — verify what that predicate requires and extend
the `student` fixture if the CANDIDATE role alone is not enough.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest payments/test_coverage.py -k "member_decision or treasurer_set_status" -q`
Expected: FAIL — the registration keeps its `$200.00` quote.

- [ ] **Step 3: Implement the member path**

In `payments/views.py`, extend the notification import block at line 43 with `notify_coverage_restored`, then replace the bill/restore block in `tuition_decision`:

```python
                # Bill or restore the events tuition coverage touches. A paying
                # decision covers that year's registrations, including ones made
                # before the decision was recorded (task #561), so committing
                # returns their access without money moving.
                if status == "skipping":
                    billed = coverage.bill_skipped_coverage(request.user, period)
                    restored = []
                else:
                    billed = []
                    restored = coverage.apply_coverage(request.user, period)
            if billed:
                notify_coverage_rebilled(request.user, period, billed)
            if restored:
                notify_coverage_restored(request.user, period, restored)
```

- [ ] **Step 4: Implement the treasurer path**

In `treasurer_tuition_set_status`, inside the existing `with transaction.atomic():` block, after `enr.save(update_fields=("notes",))`:

```python
        # A covering decision prices that year's unpaid registrations at $0
        # (task #561). Deliberately silent — the treasurer flips historical
        # years during cleanup. Skipping still does not auto-bill here: that
        # is #485's staff-paths rule, and retro-billing a cleanup pass would
        # bill years of events.
        if enr.covers_seminars:
            coverage.apply_coverage(target, period)
```

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q` then `uv run ruff check .`
Expected: PASS, clean.

- [ ] **Step 6: Commit**

```bash
git add payments/views.py payments/test_coverage.py
git commit -m "feat(payments): record a covering decision, cover the registrations (task #561)"
```

---

### Task 4: Status log and ship

**Files:**
- Modify: `CLAUDE.md` (status log entry, following the house pattern of the #485/#501 entries)

- [ ] **Step 1: Write the CLAUDE.md entry**

Add a bullet after the task #545 entry, in the established voice: what the member reported, why it happened (priced once at creation; the event's AY, not today's), the marker-matching subset argument, the Stripe-session hazard, the deliberate treasurer asymmetry, and that Matt's four rows were repaired by hand on prod first.

- [ ] **Step 2: Commit and merge to main**

```bash
git add CLAUDE.md
git commit -m "docs(core): record task #561 in the status log"
git checkout main && git merge --no-ff rapid-quartz -m "Merge rapid-quartz: apply tuition coverage to existing registrations (task #561)"
git push origin main
```

- [ ] **Step 3: Verify the deploy went green**

A push to main only deploys if the full CI suite passes. Watch it:

```bash
gh run list --repo ricopicone/lsp-website --limit 3
```

Then confirm on prod that `apply_coverage` exists in the running container and that Matt's four rows are unchanged (they were repaired by hand with these exact semantics).
