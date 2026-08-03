# Registration Payment Plans Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a faculty member mint a pricing code that splits an event fee into
N hand-paid Stripe installments, without changing the total.

**Architecture:** `PricingCode.installments` rides alongside `pricing_mode`
(the two axes stay independent). Redemption builds a `RegistrationInstallment`
schedule; the registration keeps its full `quoted_amount` and mints one
full-fee `Charge`, so the existing ledger reports it `"partial"` with no new
accounting. Access follows the existing `AWAITING_PAYMENT → PAID` flip on the
first payment.

**Tech Stack:** Django 5.2, pytest-django, Stripe hosted Checkout,
python-dateutil, Tailwind v4 + DaisyUI v5.

**Spec:** `docs/superpowers/specs/2026-08-03-registration-payment-plans-design.md`

## Global Constraints

- **A plan never changes the total.** `resolve_price` returns the same amount
  it does today; `installments` only splits it.
- **`installments=1` must be byte-identical to today's behavior.** It is the
  default and is not a special case in the code.
- **No autopay.** Every installment is a hand-clicked Stripe Checkout. No
  Stripe Subscriptions, no saved cards, no BNPL.
- **No automatic consequence for defaulting.** The lever is the treasurer's
  existing `Profile.seminar_access_suspended`. Do not add one.
- **Prose style:** unspaced em dashes (`word—word`) in code comments,
  docstrings, and docs; **member-facing site copy uses commas instead of em
  dashes** (per Annie/Diana + Rico, 2026-07-06).
- **DaisyUI semantic tokens only** in templates (`bg-base-100`,
  `text-base-content`, `badge-ghost`, …). Never `bg-gray-100`.
- **Tailwind classes set in Python must also appear in a template**, or the
  prod CSS build drops them.
- **Run from the repo root:** `uv run pytest`, `uv run ruff check .`. Both must
  be green before every commit.
- **Never add a per-page Django messages loop** — messages render once from
  `core/templates/core/_messages.html`.

---

## File Structure

**Create:**

| Path | Responsibility |
|---|---|
| `payments/registration_plans.py` | Schedule building + reading for a registration plan. Pure functions, no money movement. |
| `payments/test_registration_plans.py` | The whole feature's test suite. |
| `payments/templates/payments/email/installment_reminder.txt` | The member-facing installment nudge. |

**Modify:**

| Path | Change |
|---|---|
| `events/models.py` | `PricingCode.installments`, `Mode.FULL_PRICE`, `clean()` |
| `events/pricing.py` | `PriceResolution.installments`, `FULL_PRICE` branch |
| `events/forms.py` | `PricingCodeForm` gains `installments`; `amount_or_percent` optional for `FULL_PRICE` |
| `events/templates/events/_faculty_tools.html` | "On a plan" roster chip; "Payments" column on the codes table |
| `payments/models.py` | `RegistrationInstallment`; `Payment.registration_installment` |
| `payments/operations.py` | `complete_payment` marks the installment paid |
| `payments/charges.py` | `mint_registration_charge` bills the full fee on a plan |
| `payments/stripe_checkout.py` | `create_registration_installment_session` |
| `payments/refund.py` | `PlanRefundRequiresTreasurer(RefundError)` |
| `payments/emails.py` | `send_installment_reminder` |
| `payments/notifications.py` | `installment_reminder_inapp`, `plan_cancel_needs_treasurer` |
| `payments/management/commands/send_registration_reminders.py` | Third reminder kind |
| `payments/templates/payments/treasurer/member_detail.html` | Plan note on the registrations table |
| `registrations/models.py` | Schedule at `approve()`; cancel guard; `on_payment_plan` |
| `registrations/views.py` | Schedule at creation; installment-1 checkout; `pay_installment` |
| `workgroups/views.py` | Roster-tab prefetch (the seminar roster faculty actually use) |
| `registrations/urls.py` | `pay_installment` route |
| `registrations/templates/registrations/register_confirm.html` | Schedule block; plan-aware copy |

---

### Task 1: The code carries an installment count and a full-price mode

**Files:**
- Modify: `events/models.py:1034-1109` (`PricingCode.Mode`, fields, `clean`)
- Modify: `events/pricing.py:27-127` (`PriceResolution`, `_apply_code`)
- Create: `events/migrations/00XX_pricingcode_installments.py` (generated)
- Test: `payments/test_registration_plans.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `events.models.PricingCode.installments: int` (default `1`)
  - `events.models.PricingCode.Mode.FULL_PRICE == "full_price"`
  - `events.pricing.PriceResolution(amount, explanation, code_redeemed=None, installments=1)`

- [ ] **Step 1: Write the failing tests**

Create `payments/test_registration_plans.py`:

```python
"""Registration payment plans (task #501)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import Profile, User
from events.models import Audience, Event, PriceTier, PricingCode
from events.pricing import resolve_price

pytestmark = pytest.mark.django_db


def _user(email="member@example.com"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    return u


def _event(title="Seminar", **kwargs):
    today = timezone.localdate()
    return Event.objects.create(
        title=title,
        slug=title.lower().replace(" ", "-"),
        event_type=Event.Type.SEMINAR,
        start_date=today + timedelta(days=7),
        end_date=today + timedelta(days=90),
        published=True,
        status=Event.Status.OPEN,
        **kwargs,
    )


def _tier(event, amount="500.00", **kwargs):
    return PriceTier.objects.create(
        event=event, audience=Audience.ALL,
        base_amount=Decimal(amount), **kwargs,
    )


def _code(event, issuer, **kwargs):
    kwargs.setdefault("pricing_mode", PricingCode.Mode.FULL_PRICE)
    kwargs.setdefault("amount_or_percent", Decimal("0"))
    return PricingCode.objects.create(event=event, issued_by=issuer, **kwargs)


def test_installments_defaults_to_one():
    issuer = _user("faculty@example.com")
    event = _event()
    code = _code(event, issuer)
    assert code.installments == 1


def test_plain_code_resolution_is_unchanged():
    """installments=1 must resolve byte-identically to today."""
    issuer = _user("faculty@example.com")
    member = _user()
    event = _event()
    tier = _tier(event)
    code = _code(
        event, issuer,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("20"),
    )
    r = resolve_price(user=member, tier=tier, pricing_code=code)
    assert r.amount == Decimal("400.00")
    assert r.installments == 1


def test_full_price_mode_returns_the_tier_base():
    issuer = _user("faculty@example.com")
    member = _user()
    event = _event()
    tier = _tier(event)
    code = _code(event, issuer, installments=3)
    r = resolve_price(user=member, tier=tier, pricing_code=code)
    assert r.amount == Decimal("500.00")
    assert r.installments == 3
    assert code.code in r.explanation


def test_a_discount_and_a_plan_are_independent_axes():
    issuer = _user("faculty@example.com")
    member = _user()
    event = _event()
    tier = _tier(event)
    code = _code(
        event, issuer,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("20"),
        installments=3,
    )
    r = resolve_price(user=member, tier=tier, pricing_code=code)
    assert r.amount == Decimal("400.00")   # the plan did not change the total
    assert r.installments == 3


def test_installment_count_is_bounded():
    from django.core.exceptions import ValidationError
    issuer = _user("faculty@example.com")
    event = _event()
    code = PricingCode(
        event=event, issued_by=issuer,
        pricing_mode=PricingCode.Mode.FULL_PRICE,
        amount_or_percent=Decimal("0"),
        installments=0,
    )
    with pytest.raises(ValidationError):
        code.clean()
    code.installments = 13
    with pytest.raises(ValidationError):
        code.clean()
    code.installments = 3
    code.clean()   # no raise
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest payments/test_registration_plans.py -v`
Expected: FAIL — `PricingCode` has no attribute `installments`, `Mode` has no
`FULL_PRICE`.

- [ ] **Step 3: Add the mode and the field**

In `events/models.py`, extend `PricingCode.Mode`:

```python
    class Mode(models.TextChoices):
        PERCENT_OFF = "percent_off", _("Percent off")
        FIXED_AMOUNT = "fixed_amount", _("Fixed amount")
        SLIDING_FLOOR = "sliding_floor", _("Sliding-scale floor")
        #: No discount at all — the code exists only to carry a payment plan
        #: (task #501). ``amount_or_percent`` is unused and stored as 0.
        FULL_PRICE = "full_price", _("Full price — payment plan only")
```

Add the field immediately after `max_uses` / `uses_remaining` (before
`restricted_to_user`):

```python
    installments = models.PositiveSmallIntegerField(
        default=1,
        help_text=(
            "1 = pay in full at registration. A higher number splits the fee "
            "into that many payments, the first due at registration and the "
            "rest monthly. The total never changes."
        ),
    )
```

Replace `PricingCode.clean` with:

```python
    def clean(self):
        # Bound the schedule first — the amount checks below return early on a
        # blank amount, which would skip this.
        if self.installments is not None and not (
            1 <= self.installments <= MAX_INSTALLMENTS
        ):
            raise ValidationError({
                "installments": (
                    f"Choose between 1 and {MAX_INSTALLMENTS} payments."
                ),
            })
        # Form-level clean strips invalid fields from the instance; guard against None.
        if self.amount_or_percent is None:
            return
        if self.pricing_mode == self.Mode.PERCENT_OFF and not (
            Decimal("0") <= self.amount_or_percent <= Decimal("100")
        ):
            raise ValidationError(
                {"amount_or_percent": "percent_off requires a value between 0 and 100."}
            )
        if self.amount_or_percent < 0:
            raise ValidationError({"amount_or_percent": "Cannot be negative."})
```

Add near the top of `events/models.py`, beside the other module constants:

```python
#: Ceiling on a pricing code's installment count (task #501). A sanity bound,
#: not a policy — twelve monthly payments already outlasts any event we run.
MAX_INSTALLMENTS = 12
```

- [ ] **Step 4: Thread the count through the resolver**

In `events/pricing.py`, extend the dataclass:

```python
@dataclass
class PriceResolution:
    amount: Decimal
    explanation: str
    code_redeemed: PricingCode | None = None
    #: How many payments the amount is split into (task #501). 1 = pay in
    #: full, which is every path that does not redeem a plan-carrying code.
    installments: int = 1
```

In `_apply_code`, add the `FULL_PRICE` branch before the `else: raise`:

```python
    elif code.pricing_mode == PricingCode.Mode.FULL_PRICE:
        # The code carries no discount — it exists to carry the schedule.
        amount = tier.base_amount
        explanation = f"Full price ${amount} via code {code.code}."
```

and change the function's final return to:

```python
    return PriceResolution(
        amount=amount,
        explanation=explanation,
        code_redeemed=code,
        installments=code.installments,
    )
```

Update the `resolve_price` docstring's precedence list to note that a code may
additionally carry an installment count, which never affects the amount.

- [ ] **Step 5: Generate the migration**

Run: `uv run python manage.py makemigrations events -n pricingcode_installments`

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest payments/test_registration_plans.py events/test_pricing.py -v`
Expected: PASS, including every pre-existing `test_pricing.py` case.

- [ ] **Step 7: Commit**

```bash
git add events/models.py events/pricing.py events/migrations/ payments/test_registration_plans.py
git commit -m "feat(events): a pricing code may carry an installment count (task #501)"
```

---

### Task 2: The installment model

**Files:**
- Modify: `payments/models.py` (after `TuitionInstallment`, ~line 601; and
  `Payment` ~line 196)
- Create: `payments/migrations/00XX_registrationinstallment.py` (generated)
- Test: `payments/test_registration_plans.py`

**Interfaces:**
- Consumes: Task 1's `PricingCode.installments`.
- Produces:
  - `payments.models.RegistrationInstallment(registration, sequence, due_date, amount, paid, paid_at)` with `mark_paid(*, save=True)`
  - reverse accessor `Registration.installments`
  - `payments.models.Payment.registration_installment` (nullable FK), reverse `RegistrationInstallment.payments`

- [ ] **Step 1: Write the failing test**

Append to `payments/test_registration_plans.py`:

```python
def _registration(user, event, tier, amount="500.00", **kwargs):
    from registrations.models import Registration
    kwargs.setdefault("status", Registration.Status.AWAITING_PAYMENT)
    return Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal(amount), **kwargs,
    )


def test_installment_rows_hang_off_the_registration():
    from payments.models import RegistrationInstallment
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier)
    inst = RegistrationInstallment.objects.create(
        registration=reg, sequence=1,
        due_date=timezone.localdate(), amount=Decimal("166.66"),
    )
    assert list(reg.installments.all()) == [inst]
    assert inst.paid is False

    inst.mark_paid()
    inst.refresh_from_db()
    assert inst.paid is True
    assert inst.paid_at is not None

    before = inst.paid_at
    inst.mark_paid()          # idempotent
    inst.refresh_from_db()
    assert inst.paid_at == before


def test_installment_sequence_is_unique_per_registration():
    from django.db import IntegrityError
    from payments.models import RegistrationInstallment
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier)
    RegistrationInstallment.objects.create(
        registration=reg, sequence=1,
        due_date=timezone.localdate(), amount=Decimal("250.00"),
    )
    with pytest.raises(IntegrityError):
        RegistrationInstallment.objects.create(
            registration=reg, sequence=1,
            due_date=timezone.localdate(), amount=Decimal("250.00"),
        )


def test_a_payment_can_point_at_an_installment():
    from payments.models import Payment, RegistrationInstallment
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier)
    inst = RegistrationInstallment.objects.create(
        registration=reg, sequence=1,
        due_date=timezone.localdate(), amount=Decimal("166.66"),
    )
    p = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, registration=reg,
        user=member, amount=Decimal("166.66"),
        registration_installment=inst,
    )
    assert list(inst.payments.all()) == [p]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest payments/test_registration_plans.py -k installment -v`
Expected: FAIL — `cannot import name 'RegistrationInstallment'`.

- [ ] **Step 3: Add the model**

In `payments/models.py`, immediately after the `TuitionInstallment` class:

```python
class RegistrationInstallment(models.Model):
    """One installment of a payment-plan event registration (task #501).

    The twin of :class:`TuitionInstallment`, for a single seminar or reading
    group instead of a year of tuition. The registration keeps its full
    ``quoted_amount`` and mints one full-fee ``Charge``; these rows only split
    that one debt into payable chunks, exactly as the tuition plan does.

    Deliberately a separate model rather than a generalization of its twin:
    unifying them would rewrite the load-bearing tuition plumbing shipped in
    task #494 for no behavior gain.
    """

    registration = models.ForeignKey(
        "registrations.Registration",
        on_delete=models.CASCADE,
        related_name="installments",
    )
    sequence = models.PositiveSmallIntegerField(help_text="1-indexed order within the plan.")
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("registration", "sequence")
        constraints = [
            models.UniqueConstraint(
                fields=("registration", "sequence"),
                name="payments_unique_registration_installment_sequence",
            ),
        ]

    def __str__(self):
        return f"{self.registration} #{self.sequence} due {self.due_date}"

    def mark_paid(self, *, save=True) -> None:
        if self.paid:
            return
        self.paid = True
        if self.paid_at is None:
            self.paid_at = timezone.now()
        if save:
            self.save(update_fields=("paid", "paid_at"))
```

In `Payment`, immediately after the `tuition_installment` field:

```python
    registration_installment = models.ForeignKey(
        "payments.RegistrationInstallment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payments",
        help_text="The registration installment this payment satisfies — set "
                  "for a payment-plan registration (task #501).",
    )
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations payments -n registration_installment`

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest payments/test_registration_plans.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add payments/models.py payments/migrations/ payments/test_registration_plans.py
git commit -m "feat(payments): RegistrationInstallment + Payment FK (task #501)"
```

---

### Task 3: The schedule module

**Files:**
- Create: `payments/registration_plans.py`
- Test: `payments/test_registration_plans.py`

**Interfaces:**
- Consumes: Task 2's `RegistrationInstallment`.
- Produces:
  - `build_schedule(registration, count: int, *, today: date | None = None) -> list[RegistrationInstallment]`
  - `due_installment(registration, today: date, *, lead_days: int = LEAD_DAYS) -> RegistrationInstallment | None`
  - `next_unpaid(registration) -> RegistrationInstallment | None`
  - `is_on_plan(registration) -> bool`
  - `outstanding(registration) -> Decimal`
  - `LEAD_DAYS = 7`

- [ ] **Step 1: Write the failing tests**

Append to `payments/test_registration_plans.py`:

```python
def test_schedule_sums_to_the_exact_fee_with_the_remainder_last():
    from payments import registration_plans
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier, "500.00")

    rows = registration_plans.build_schedule(reg, 3, today=date(2026, 9, 1))
    assert [r.amount for r in rows] == [
        Decimal("166.66"), Decimal("166.66"), Decimal("166.68"),
    ]
    assert sum(r.amount for r in rows) == Decimal("500.00")
    assert [r.due_date for r in rows] == [
        date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1),
    ]


def test_build_schedule_is_idempotent():
    from payments import registration_plans
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier)

    first = registration_plans.build_schedule(reg, 3, today=date(2026, 9, 1))
    again = registration_plans.build_schedule(reg, 5, today=date(2026, 9, 1))
    assert len(first) == 3
    assert len(again) == 3
    assert reg.installments.count() == 3


def test_build_schedule_declines_degenerate_input():
    from payments import registration_plans
    member = _user()
    event = _event()
    tier = _tier(event)

    reg = _registration(member, event, tier)
    assert registration_plans.build_schedule(reg, 1) == []
    assert reg.installments.count() == 0

    free = _registration(_user("free@example.com"), event, tier, "0.00")
    assert registration_plans.build_schedule(free, 3) == []


def test_plan_readers():
    from payments import registration_plans
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier, "300.00")

    assert registration_plans.is_on_plan(reg) is False
    registration_plans.build_schedule(reg, 3, today=date(2026, 9, 1))
    assert registration_plans.is_on_plan(reg) is True
    assert registration_plans.outstanding(reg) == Decimal("300.00")

    first = registration_plans.next_unpaid(reg)
    assert first.sequence == 1
    first.mark_paid()
    assert registration_plans.next_unpaid(reg).sequence == 2
    assert registration_plans.outstanding(reg) == Decimal("200.00")


def test_due_installment_prefers_the_oldest_overdue():
    from payments import registration_plans
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier, "300.00")
    registration_plans.build_schedule(reg, 3, today=date(2026, 9, 1))

    # Nothing due a month before the schedule starts.
    assert registration_plans.due_installment(reg, date(2026, 8, 1)) is None
    # Within the lead window ahead of #1.
    assert registration_plans.due_installment(reg, date(2026, 8, 28)).sequence == 1
    # #1 unpaid and overdue wins over #2 falling due.
    assert registration_plans.due_installment(reg, date(2026, 10, 1)).sequence == 1

    reg.installments.filter(sequence=1).update(paid=True)
    assert registration_plans.due_installment(reg, date(2026, 10, 1)).sequence == 2
    reg.installments.update(paid=True)
    assert registration_plans.due_installment(reg, date(2026, 12, 1)) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest payments/test_registration_plans.py -k "schedule or plan_readers or due_installment" -v`
Expected: FAIL — `No module named 'payments.registration_plans'`.

- [ ] **Step 3: Write the module**

Create `payments/registration_plans.py`:

```python
"""Registration payment-plan schedules (task #501).

The sibling of :mod:`payments.plans`, which answers the same questions for a
tuition enrollment. Kept separate rather than generalized: the two share a
shape, not a caller, and unifying them would rewrite the tuition plumbing
shipped in task #494 for no behavior gain.

Nothing here mints or moves money. A plan never changes what is owed — the
registration keeps its full ``quoted_amount`` and mints one full-fee
``Charge`` — these rows only split that one debt into payable chunks.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal

from dateutil.relativedelta import relativedelta
from django.db.models import Sum
from django.utils import timezone

from .models import RegistrationInstallment

#: How far ahead of its due date an installment starts being nudged. Matched
#: to :data:`payments.plans.LEAD_DAYS` so a member on both a tuition plan and
#: an event plan is nudged on the same rhythm.
LEAD_DAYS = 7

CENT = Decimal("0.01")


def build_schedule(
    registration, count: int, *, today: date | None = None,
) -> list[RegistrationInstallment]:
    """Create the installment rows for ``registration``, or return the
    existing ones.

    Even split with the rounding remainder on the **final** installment, so
    the schedule sums to the fee exactly. Installment 1 is due ``today``; the
    rest fall monthly. Idempotent — a registration that already carries a
    schedule keeps it, whatever ``count`` says.

    Returns ``[]`` for a degenerate request (fewer than two installments, or a
    non-positive fee); those are the ordinary pay-in-full path, not a plan.
    """
    existing = list(registration.installments.order_by("sequence"))
    if existing:
        return existing
    if count < 2:
        return []
    total = Decimal(registration.quoted_amount)
    if total <= 0:
        return []

    today = today or timezone.localdate()
    each = (total / count).quantize(CENT, rounding=ROUND_DOWN)
    rows = [
        RegistrationInstallment(
            registration=registration,
            sequence=i,
            due_date=today + relativedelta(months=i - 1),
            amount=(each if i < count else total - each * (count - 1)),
        )
        for i in range(1, count + 1)
    ]
    return RegistrationInstallment.objects.bulk_create(rows)


def is_on_plan(registration) -> bool:
    """Whether this registration is being paid in installments.

    Any schedule at all means a plan: :func:`build_schedule` never writes
    fewer than two rows.

    Reads ``.all()`` rather than ``.exists()`` on purpose — the roster surfaces
    call this per row, and ``.all()`` uses a ``prefetch_related("installments")``
    cache where ``.exists()`` would fire a query anyway. Uncached it is still
    one query for at most twelve tiny rows.
    """
    return bool(registration.installments.all())


def next_unpaid(registration) -> RegistrationInstallment | None:
    """The earliest unpaid installment, regardless of due date — what a member
    pays next, including paying ahead."""
    return registration.installments.filter(paid=False).order_by("sequence").first()


def due_installment(
    registration, today: date, *, lead_days: int = LEAD_DAYS,
) -> RegistrationInstallment | None:
    """The unpaid installment needing attention, or ``None``.

    The oldest overdue one wins; failing that, the earliest one falling due
    within ``lead_days``. Ordering by due date (not sequence) means a
    treasurer's hand-edited schedule still reads correctly — the same rule
    :func:`payments.plans.due_installment` uses.
    """
    return (
        registration.installments
        .filter(paid=False, due_date__lte=today + timedelta(days=lead_days))
        .order_by("due_date", "sequence")
        .first()
    )


def outstanding(registration) -> Decimal:
    """Sum of the unpaid installments. Zero when there is no plan."""
    total = registration.installments.filter(paid=False).aggregate(
        total=Sum("amount"),
    )["total"]
    return total or Decimal("0.00")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest payments/test_registration_plans.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add payments/registration_plans.py payments/test_registration_plans.py
git commit -m "feat(payments): registration plan schedule module (task #501)"
```

---

### Task 4: Settlement bills the full fee and marks the installment

**Files:**
- Modify: `payments/charges.py:219-245` (`mint_registration_charge`)
- Modify: `payments/operations.py:27-78` (`complete_payment`)
- Test: `payments/test_registration_plans.py`

**Interfaces:**
- Consumes: Task 3's `is_on_plan`; Task 2's `Payment.registration_installment`.
- Produces: no new names. `mint_registration_charge(payment)` keeps its
  signature and return type (`Charge | None`).

**Why this precedes the registration flow:** the charge must already be
correct by the time anything creates a plan registration for real.

- [ ] **Step 1: Write the failing tests**

Append to `payments/test_registration_plans.py`:

```python
def _settle(reg, installment):
    """Pay one installment the way the Stripe webhook does."""
    from payments.models import Payment
    from payments.operations import complete_payment
    p = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, registration=reg,
        user=reg.user, amount=installment.amount,
        method=Payment.Method.STRIPE, status=Payment.Status.PENDING,
        registration_installment=installment,
        stripe_payment_intent_id=f"pi_test_{installment.pk}",
    )
    complete_payment(p)
    return p


def test_a_plan_mints_one_charge_for_the_whole_fee():
    from payments import registration_plans
    from payments.models import Charge
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier, "500.00")
    rows = registration_plans.build_schedule(reg, 3, today=timezone.localdate())

    _settle(reg, rows[0])
    charges = Charge.objects.filter(registration=reg)
    assert charges.count() == 1
    # The full fee, not the $166.66 that actually moved.
    assert charges.first().amount == Decimal("500.00")

    _settle(reg, rows[1])
    _settle(reg, rows[2])
    assert Charge.objects.filter(registration=reg).count() == 1


def test_a_non_plan_registration_mints_exactly_what_it_did_before():
    from payments.models import Charge, Payment
    from payments.operations import complete_payment
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier, "500.00")
    p = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, registration=reg,
        user=member, amount=Decimal("500.00"),
        method=Payment.Method.STRIPE, status=Payment.Status.PENDING,
        stripe_payment_intent_id="pi_test_plain",
    )
    complete_payment(p)
    assert Charge.objects.get(registration=reg).amount == Decimal("500.00")


def test_settling_an_installment_marks_it_and_grants_access():
    from registrations.models import Registration
    from payments import registration_plans
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier, "300.00")
    rows = registration_plans.build_schedule(reg, 3, today=timezone.localdate())

    _settle(reg, rows[0])
    rows[0].refresh_from_db()
    reg.refresh_from_db()
    assert rows[0].paid is True
    # Access follows the first payment — the existing AWAITING_PAYMENT flip.
    assert reg.status == Registration.Status.PAID
    assert registration_plans.outstanding(reg) == Decimal("200.00")


def test_the_ledger_reads_partial_until_the_last_installment():
    from payments import registration_plans
    from payments.ledger import member_account
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier, "300.00")
    rows = registration_plans.build_schedule(reg, 3, today=timezone.localdate())

    _settle(reg, rows[0])
    account = member_account(member)
    assert account["balance"] == Decimal("200.00")

    _settle(reg, rows[1])
    assert member_account(member)["balance"] == Decimal("100.00")

    _settle(reg, rows[2])
    assert member_account(member)["balance"] == Decimal("0.00")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest payments/test_registration_plans.py -k "mints or settling or ledger_reads" -v`
Expected: FAIL — the charge is $166.66, and the installment is not marked paid.

- [ ] **Step 3: Bill the full fee on a plan**

In `payments/charges.py`, inside `mint_registration_charge`, after the
`existing is not None` early return and before `Charge.objects.create`:

```python
    from .registration_plans import is_on_plan

    registration = payment.registration
    # A payment plan pays one debt in chunks: the school billed the whole fee,
    # so that is what the ledger records. Without this a $500 seminar paid in
    # three would enter the books as a $166.66 obligation (task #501). Scoped
    # to plan registrations so no ordinary row's provenance shifts.
    amount = (
        registration.quoted_amount if is_on_plan(registration)
        else payment.amount
    )
```

and change the `Charge.objects.create(...)` call's `amount=payment.amount` to
`amount=amount`.

- [ ] **Step 4: Mark the installment at settle**

In `payments/operations.py`, inside `complete_payment`'s atomic block,
immediately after the existing tuition branch:

```python
        if payment.registration_installment_id:
            payment.registration_installment.mark_paid()
```

Extend the `complete_payment` docstring: "For a payment-plan registration,
additionally mark the linked ``RegistrationInstallment`` paid. The
registration's ``AWAITING_PAYMENT → PAID`` flip is unchanged and happens on
the first installment — on a plan, ``PAID`` means enrolled, and the ledger
holds the truth about what is still owed."

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest payments/test_registration_plans.py payments/test_registration_charges.py payments/test_webhook.py -v`
Expected: PASS, including the pre-existing charge and webhook suites.

- [ ] **Step 6: Commit**

```bash
git add payments/charges.py payments/operations.py payments/test_registration_plans.py
git commit -m "fix(payments): a plan registration is billed the whole fee (task #501)"
```

---

### Task 5: Redeeming a plan code builds the schedule and charges installment 1

**Files:**
- Modify: `registrations/views.py:66-97` (`_create_registration`), `:206-213`
  (the checkout redirect)
- Modify: `registrations/models.py:166-190` (`approve`)
- Modify: `payments/stripe_checkout.py` (new session builder)
- Test: `payments/test_registration_plans.py`

**Interfaces:**
- Consumes: Task 3's `build_schedule` / `next_unpaid`; Task 1's
  `PriceResolution.installments`.
- Produces:
  - `payments.stripe_checkout.create_registration_installment_session(installment) -> tuple[Payment, stripe.checkout.Session]`

- [ ] **Step 1: Write the failing tests**

Append to `payments/test_registration_plans.py`:

```python
def test_redeeming_a_plan_code_builds_the_schedule(client, monkeypatch):
    from registrations.models import Registration
    member = _user()
    issuer = _user("faculty@example.com")
    event = _event()
    tier = _tier(event, "500.00")
    code = _code(event, issuer, installments=3)

    sessions = []

    def _fake(installment):
        from payments.models import Payment
        p = Payment.objects.create(
            payment_type=Payment.Type.REGISTRATION,
            registration=installment.registration,
            user=installment.registration.user, amount=installment.amount,
            method=Payment.Method.STRIPE, status=Payment.Status.PENDING,
            registration_installment=installment,
        )
        sessions.append(p)
        return p, type("S", (), {"url": "https://stripe.test/session"})()

    monkeypatch.setattr(
        "registrations.views.create_registration_installment_session", _fake,
    )

    client.force_login(member)
    resp = client.post(
        f"/events/{event.slug}/register/",
        {"price_tier": tier.pk, "pricing_code": code.code},
    )
    assert resp.status_code == 302

    reg = Registration.objects.get(user=member, event=event)
    assert reg.quoted_amount == Decimal("500.00")      # the full fee
    assert reg.installments.count() == 3
    # Checkout was opened for installment 1 only.
    assert len(sessions) == 1
    assert sessions[0].amount == Decimal("166.66")


def test_an_approval_gated_plan_builds_its_schedule_on_approval():
    from registrations.models import Registration
    member = _user()
    issuer = _user("faculty@example.com")
    event = _event(requires_faculty_approval=True)
    tier = _tier(event, "300.00")
    code = _code(event, issuer, installments=3)

    reg = _registration(
        member, event, tier, "300.00",
        status=Registration.Status.PENDING_APPROVAL, pricing_code=code,
    )
    assert reg.installments.count() == 0

    reg.approve(issuer)
    reg.refresh_from_db()
    assert reg.status == Registration.Status.AWAITING_PAYMENT
    assert reg.installments.count() == 3


def test_a_declined_plan_registration_builds_no_schedule():
    from registrations.models import Registration
    member = _user()
    issuer = _user("faculty@example.com")
    event = _event(requires_faculty_approval=True)
    tier = _tier(event, "300.00")
    code = _code(event, issuer, installments=3)
    reg = _registration(
        member, event, tier, "300.00",
        status=Registration.Status.PENDING_APPROVAL, pricing_code=code,
    )
    reg.decline(issuer, "no")
    assert reg.installments.count() == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest payments/test_registration_plans.py -k "redeeming or approval_gated or declined_plan" -v`
Expected: FAIL — no schedule is built.

- [ ] **Step 3: Add the installment checkout session**

In `payments/stripe_checkout.py`, after `create_checkout_session`:

```python
def create_registration_installment_session(
    installment,
) -> tuple[Payment, stripe.checkout.Session]:
    """Build a Checkout Session for one installment of a plan registration
    (task #501).

    The twin of :func:`create_tuition_session`, minting its own Payment the
    way :func:`create_checkout_session` does — a plan pays the same
    registration several times, so each attempt needs its own row.
    """
    registration = installment.registration
    total = registration.installments.count()

    payment = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=registration,
        user=registration.user,
        amount=installment.amount,
        method=Payment.Method.STRIPE,
        status=Payment.Status.PENDING,
        registration_installment=installment,
    )

    session = _make_session(
        payment=payment,
        product_name=registration.event.title,
        product_description=(
            f"Payment {installment.sequence} of {total} "
            f"(${registration.quoted_amount} total)"
        ),
        success_path=(
            reverse("registrations:confirm", args=[registration.id])
            + "?stripe=success"
        ),
        cancel_path=(
            reverse("registrations:confirm", args=[registration.id])
            + "?stripe=cancelled"
        ),
    )
    return payment, session
```

- [ ] **Step 4: Build the schedule at registration**

In `registrations/views.py`, import at the top:

```python
from payments import registration_plans
from payments.stripe_checkout import create_registration_installment_session
```

In `_create_registration`, inside the `with transaction.atomic():` block after
`reg = Registration.objects.create(...)` and before the code-consumption
block:

```python
        # A plan-carrying code splits the fee (task #501). The registration
        # keeps the full quoted_amount; only the payment is chunked. An
        # approval-gated registration waits — its schedule is built at
        # approve(), so a fortnight in the queue doesn't make installment 1
        # overdue on arrival.
        if resolution.installments > 1 and not requires_approval:
            registration_plans.build_schedule(reg, resolution.installments)
```

In `register_for_event`, replace the final checkout redirect:

```python
            _payment, session = create_checkout_session(reg)
            return redirect(session.url)
```

with:

```python
            first = registration_plans.next_unpaid(reg)
            if first is not None:
                _payment, session = create_registration_installment_session(first)
            else:
                _payment, session = create_checkout_session(reg)
            return redirect(session.url)
```

- [ ] **Step 5: Build the schedule at approval**

In `registrations/models.py`, inside `approve`, after the pricing-code
consumption block and before the status assignment:

```python
        # A plan-carrying code splits the fee (task #501). Built here rather
        # than at registration so the schedule starts the day the place is
        # confirmed, not the day it was requested.
        if self.pricing_code_id and self.quoted_amount > 0:
            from payments.registration_plans import build_schedule
            build_schedule(self, self.pricing_code.installments)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest payments/test_registration_plans.py registrations/ -v`
Expected: PASS, including the pre-existing registration suites.

- [ ] **Step 7: Commit**

```bash
git add registrations/views.py registrations/models.py payments/stripe_checkout.py payments/test_registration_plans.py
git commit -m "feat(registrations): a plan code splits the fee at redemption (task #501)"
```

---

### Task 6: The member pays the rest

**Files:**
- Modify: `registrations/views.py` (new `pay_installment`,
  `registration_confirm` context)
- Modify: `registrations/urls.py`
- Modify: `registrations/templates/registrations/register_confirm.html:51-72`
- Test: `payments/test_registration_plans.py`

**Interfaces:**
- Consumes: Task 5's `create_registration_installment_session`; Task 3's
  readers.
- Produces: URL name `registrations:pay_installment` taking `installment_id`.

- [ ] **Step 1: Write the failing tests**

Append to `payments/test_registration_plans.py`:

```python
def test_a_member_can_pay_a_later_installment(client, monkeypatch):
    from payments import registration_plans
    from registrations.models import Registration
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    rows = registration_plans.build_schedule(reg, 3, today=timezone.localdate())
    rows[0].mark_paid()

    called = {}

    def _fake(installment):
        called["seq"] = installment.sequence
        return None, type("S", (), {"url": "https://stripe.test/session"})()

    monkeypatch.setattr(
        "registrations.views.create_registration_installment_session", _fake,
    )

    client.force_login(member)
    resp = client.post(f"/registrations/installments/{rows[1].pk}/pay/")
    assert resp.status_code == 302
    assert called["seq"] == 2


def test_paying_a_paid_installment_is_a_no_op(client):
    from payments import registration_plans
    from registrations.models import Registration
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    rows = registration_plans.build_schedule(reg, 3, today=timezone.localdate())
    rows[0].mark_paid()

    client.force_login(member)
    resp = client.post(f"/registrations/installments/{rows[0].pk}/pay/")
    assert resp.status_code == 302
    assert f"/registrations/{reg.pk}/confirmation/" in resp["Location"]


def test_another_member_cannot_pay_your_installment(client):
    from payments import registration_plans
    from registrations.models import Registration
    member = _user()
    intruder = _user("intruder@example.com")
    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    rows = registration_plans.build_schedule(reg, 3, today=timezone.localdate())

    client.force_login(intruder)
    resp = client.post(f"/registrations/installments/{rows[0].pk}/pay/")
    assert resp.status_code == 404


def test_the_confirmation_page_shows_the_schedule(client):
    from payments import registration_plans
    from registrations.models import Registration
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    rows = registration_plans.build_schedule(reg, 3, today=timezone.localdate())
    rows[0].mark_paid()

    client.force_login(member)
    body = client.get(f"/registrations/{reg.pk}/confirmation/").content.decode()
    assert "payment plan" in body.lower()
    assert "$200.00" in body            # still to pay
    assert "you're all set" not in body.lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest payments/test_registration_plans.py -k "pay_a_later or no_op or another_member or confirmation_page" -v`
Expected: FAIL — 404 on the URL; the confirmation page says "you're all set".

- [ ] **Step 3: Add the view**

In `registrations/views.py`, after `pay_registration`:

```python
@login_required
@require_POST
def pay_installment(request, installment_id: int):
    """The registrant pays one installment of a payment-plan registration
    (task #501). Owner-only; a paid installment is a no-op redirect."""
    from payments.models import RegistrationInstallment

    installment = get_object_or_404(
        RegistrationInstallment.objects.select_related(
            "registration", "registration__event",
        ),
        pk=installment_id, registration__user=request.user,
    )
    if installment.paid:
        return redirect(
            "registrations:confirm", reg_id=installment.registration_id,
        )
    _payment, session = create_registration_installment_session(installment)
    return redirect(session.url)
```

- [ ] **Step 4: Add the route**

In `registrations/urls.py`, after the `pay` path:

```python
    path(
        "registrations/installments/<int:installment_id>/pay/",
        views.pay_installment,
        name="pay_installment",
    ),
```

- [ ] **Step 5: Give the confirmation page the plan context**

In `registrations/views.py`, `registration_confirm`, add to the context dict:

```python
            "installments": list(reg.installments.all()),
            "outstanding": registration_plans.outstanding(reg),
            "today": timezone.localdate(),
```

Add `from django.utils import timezone` to the imports if it is not already
there.

- [ ] **Step 6: Render the schedule**

In `registrations/templates/registrations/register_confirm.html`, change the
`{% elif registration.status == "paid" %}` branch to:

```html
  {% elif registration.status == "paid" and installments and outstanding > 0 %}
  <div role="alert" class="alert alert-info">
    <span>Your place is confirmed. You're paying in installments, so ${{ outstanding }} is still to come.</span>
  </div>
  {% elif registration.status == "paid" %}
  <p class="text-base-content/80">
    Payment received — you're all set. Access details have been emailed.
  </p>
  {% endif %}
```

> Careful: the original block ends with `{% endif %}` already — replace the
> single `{% elif ... "paid" %}` arm with the two arms above, leaving the
> `declined` arm and the closing `{% endif %}` intact.

Then, immediately after that `{% endif %}`, add the schedule table:

```html
  {% if installments %}
  <div class="space-y-3">
    <h2 class="font-serif text-lg text-base-content">Your payment plan</h2>
    <div class="overflow-x-auto rounded-lg border border-base-300">
      <table class="table table-sm">
        <thead>
          <tr><th>Payment</th><th>Due</th><th class="whitespace-nowrap">Amount</th><th></th></tr>
        </thead>
        <tbody>
        {% for inst in installments %}
          <tr>
            <td>{{ inst.sequence }} of {{ installments|length }}</td>
            <td class="whitespace-nowrap">{{ inst.due_date|date:"M j, Y" }}</td>
            <td class="whitespace-nowrap">${{ inst.amount }}</td>
            <td class="text-right">
              {% if inst.paid %}
                <span class="badge badge-sm badge-success">Paid</span>
              {% else %}
                <form method="post" action="{% url 'registrations:pay_installment' inst.id %}" style="display:contents">
                  {% csrf_token %}
                  <button type="submit" class="btn btn-xs {% if inst.due_date <= today %}btn-primary{% else %}btn-ghost{% endif %}">
                    Pay ${{ inst.amount }} →
                  </button>
                </form>
              {% endif %}
            </td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
    <p class="text-xs text-base-content/60">
      Your place is held for the whole event, you don't need to wait for the
      last payment. If your circumstances change, contact the treasurer.
    </p>
  </div>
  {% endif %}
```

Finally, in the cancel form's `onsubmit` confirm text and button label,
suppress the "(full refund)" promise for a plan — change the button label
line to:

```html
      {% if registration.status == "pending_approval" %}Withdraw request{% else %}Cancel registration{% if registration.status == "paid" and not installments %} (full refund){% endif %}{% endif %}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest payments/test_registration_plans.py registrations/ -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add registrations/views.py registrations/urls.py registrations/templates/registrations/register_confirm.html payments/test_registration_plans.py
git commit -m "feat(registrations): members pay plan installments from the confirmation page (task #501)"
```

---

### Task 7: Self-service cancel refuses on a plan

**Files:**
- Modify: `payments/refund.py:20-22` (new exception)
- Modify: `registrations/models.py:126-158` (`cancel`)
- Modify: `registrations/views.py:255-285` (`cancel_registration`)
- Modify: `payments/notifications.py`
- Test: `payments/test_registration_plans.py`

**Interfaces:**
- Consumes: Task 3's `is_on_plan`.
- Produces:
  - `payments.refund.PlanRefundRequiresTreasurer(RefundError)`
  - `payments.notifications.plan_cancel_needs_treasurer(registration) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `payments/test_registration_plans.py`:

```python
def test_a_plan_registration_refuses_self_cancel():
    from payments import registration_plans
    from payments.refund import PlanRefundRequiresTreasurer
    from registrations.models import Registration
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    registration_plans.build_schedule(reg, 3, today=timezone.localdate())

    with pytest.raises(PlanRefundRequiresTreasurer):
        reg.cancel()
    reg.refresh_from_db()
    assert reg.status == Registration.Status.PAID   # nothing moved


def test_the_cancel_view_tells_the_member_to_ask_the_treasurer(client):
    from payments import registration_plans
    from registrations.models import Registration
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    registration_plans.build_schedule(reg, 3, today=timezone.localdate())

    client.force_login(member)
    resp = client.post(f"/registrations/{reg.pk}/cancel/", follow=True)
    body = resp.content.decode().lower()
    assert "treasurer" in body
    reg.refresh_from_db()
    assert reg.status == Registration.Status.PAID


def test_an_ordinary_paid_registration_still_self_cancels(monkeypatch):
    from payments.models import Payment
    from registrations.models import Registration
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, registration=reg, user=member,
        amount=Decimal("300.00"), method=Payment.Method.STRIPE,
        status=Payment.Status.SUCCEEDED, stripe_payment_intent_id="pi_ok",
    )
    monkeypatch.setattr(
        "payments.refund.refund_payment", lambda p: {"id": "re_test"},
    )
    reg.cancel()
    reg.refresh_from_db()
    assert reg.status == Registration.Status.REFUNDED
```

> **Note for the implementer:** `Registration.cancel` imports
> `refund_payment` *inside* the method, so `monkeypatch.setattr` on
> `payments.refund.refund_payment` is what takes effect. Keep that import
> style.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest payments/test_registration_plans.py -k "refuses_self_cancel or tells_the_member or still_self_cancels" -v`
Expected: FAIL — `cannot import name 'PlanRefundRequiresTreasurer'`.

- [ ] **Step 3: Add the exception**

In `payments/refund.py`, after `RefundError`:

```python
class PlanRefundRequiresTreasurer(RefundError):
    """Raised when a registration cannot be self-cancelled because more than
    one payment settled it (task #501).

    A member who attended four of ten sessions and stops paying is a
    pro-rating conversation, not a full refund, and pro-rating is the kind of
    judgment the school reserves for a person (architecture §4.1).
    """
```

- [ ] **Step 4: Guard the cancel**

In `registrations/models.py`, inside `cancel`, replace the opening of the
`if self.status == self.Status.PAID:` branch:

```python
            if self.status == self.Status.PAID:
                from payments.refund import PlanRefundRequiresTreasurer
                from payments.registration_plans import is_on_plan

                succeeded = self.payments.filter(
                    status=_Payment.Status.SUCCEEDED,
                    method=_Payment.Method.STRIPE,
                )
                # A plan pays one registration several times. Refunding the
                # first row we find would under-refund and call the whole
                # thing refunded — a latent bug for any multi-payment
                # registration, not only a plan (task #501).
                if is_on_plan(self) or succeeded.count() > 1:
                    raise PlanRefundRequiresTreasurer(
                        "This registration was paid in installments; the "
                        "treasurer settles the refund by hand."
                    )
                payment = succeeded.first()
```

(The existing `if payment is None: raise RuntimeError(...)` and the lines
below it stay exactly as they are.)

- [ ] **Step 5: Handle it in the view**

In `registrations/views.py`, `cancel_registration`, replace the
`except RefundError as exc:` block with:

```python
    except PlanRefundRequiresTreasurer:
        notify_payments.plan_cancel_needs_treasurer(reg)
        messages.info(
            request,
            "Because you're paying for this in installments, the treasurer "
            "handles the cancellation. We've let them know, and they'll be "
            "in touch about the payments already made.",
        )
        return redirect("registrations:confirm", reg_id=reg.id)
    except RefundError as exc:
        # ... unchanged ...
```

Add `PlanRefundRequiresTreasurer` to the existing `from payments.refund import
RefundError` line. **Order matters** — the subclass must be caught first.

- [ ] **Step 6: Notify the treasurer**

In `payments/notifications.py`:

```python
def plan_cancel_needs_treasurer(registration) -> None:
    """Tell the treasurer a payment-plan registrant asked to cancel (task
    #501). The site deliberately refuses to decide the refund."""
    from core.models import StaffRole

    role = StaffRole.objects.filter(key=StaffRole.TREASURER).first()
    holders = list(role.holders.all()) if role else []
    if not holders:
        log.warning(
            "plan_cancel_needs_treasurer: no Treasurer role holder — "
            "registration %s cancellation request unseen", registration.pk,
        )
        return
    who = registration.user.get_full_name() or registration.user.email
    for user in holders:
        notify(
            user, Category.ACCOUNT_UPDATES,
            title=f"Cancellation request on a payment plan: {who}",
            body=(
                f"{who} asked to cancel their registration for "
                f"\"{registration.event.title}\" (${registration.quoted_amount} "
                "on a payment plan). The refund needs your decision."
            ),
            url=reverse("treasurer_member_detail", args=[registration.user_id]),
            target=registration, dedupe=True,
        )
```

`reverse` is already imported in `payments/notifications.py`; if not, add
`from django.urls import reverse`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest payments/test_registration_plans.py registrations/test_cancel.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add payments/refund.py payments/notifications.py registrations/models.py registrations/views.py payments/test_registration_plans.py
git commit -m "fix(registrations): a multi-payment registration can't self-refund (task #501)"
```

---

### Task 8: Installment reminders

**Files:**
- Modify: `payments/management/commands/send_registration_reminders.py:69-96`
- Modify: `payments/emails.py` (after `send_payment_reminder`, ~line 346)
- Modify: `payments/notifications.py` (after `payment_reminder_inapp`, ~line 78)
- Create: `payments/templates/payments/email/installment_reminder.txt`
- Test: `payments/test_registration_plans.py`

**Interfaces:**
- Consumes: Task 3's `due_installment` / `outstanding`.
- Produces:
  - `payments.emails.send_installment_reminder(installment) -> None`
  - `payments.notifications.installment_reminder_inapp(installment) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `payments/test_registration_plans.py`:

```python
def _run_reminders(**opts):
    from django.core.management import call_command
    from io import StringIO
    out = StringIO()
    call_command("send_registration_reminders", stdout=out, **opts)
    return out.getvalue()


def test_an_overdue_installment_is_nudged(mailoutbox):
    from payments import registration_plans
    from registrations.models import Registration
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    registration_plans.build_schedule(
        reg, 3, today=timezone.localdate() - timedelta(days=40),
    )
    _run_reminders()
    assert len(mailoutbox) == 1
    assert "payment" in mailoutbox[0].subject.lower()
    reg.refresh_from_db()
    assert reg.reminded_at is not None


def test_a_fully_paid_plan_is_not_nudged(mailoutbox):
    from payments import registration_plans
    from registrations.models import Registration
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    registration_plans.build_schedule(
        reg, 3, today=timezone.localdate() - timedelta(days=40),
    )
    reg.installments.update(paid=True)
    _run_reminders()
    assert len(mailoutbox) == 0


def test_an_installment_far_in_the_future_is_not_nudged(mailoutbox):
    from payments import registration_plans
    from registrations.models import Registration
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    registration_plans.build_schedule(
        reg, 3, today=timezone.localdate() + timedelta(days=60),
    )
    _run_reminders()
    assert len(mailoutbox) == 0


def test_the_installment_nudge_is_throttled(mailoutbox):
    from payments import registration_plans
    from registrations.models import Registration
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    registration_plans.build_schedule(
        reg, 3, today=timezone.localdate() - timedelta(days=40),
    )
    _run_reminders()
    _run_reminders()
    assert len(mailoutbox) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest payments/test_registration_plans.py -k "nudged or throttled" -v`
Expected: FAIL — no mail is sent.

- [ ] **Step 3: Write the email template**

Create `payments/templates/payments/email/installment_reminder.txt`:

```
{% autoescape off %}{{ registration.user.first_name|default:"Hello" }},

This is a reminder about your payment plan for "{{ registration.event.title }}".

Payment {{ installment.sequence }} of {{ total }}:  ${{ installment.amount }}
Due:                                                {{ installment.due_date }}
Still to pay:                                       ${{ outstanding }}

Make this payment here:
{{ confirm_url }}

Your place in the event is confirmed, this is only about the remaining
payments. If your circumstances have changed, reply and we'll sort something
out.

Questions? Reply to this email, it goes to {{ support_email }}.

— Lacanian School of Psychoanalysis
{% endautoescape %}
```

- [ ] **Step 4: Add the sender**

In `payments/emails.py`, after `send_payment_reminder`:

```python
def send_installment_reminder(installment) -> None:
    """Nudge a registrant about the next payment on their plan (task #501)."""
    from . import registration_plans

    registration = installment.registration
    subject = (
        f"Reminder: payment {installment.sequence} for "
        f"{registration.event.title}"
    )
    with _recipient_timezone(registration.user):
        body = render_to_string(
            "payments/email/installment_reminder.txt",
            {
                "registration": registration,
                "installment": installment,
                "total": registration.installments.count(),
                "outstanding": registration_plans.outstanding(registration),
                "confirm_url": _confirm_url(registration),
                "support_email": settings.SUPPORT_EMAIL,
            },
        )
    _send(subject=subject, body=body, to=[registration.user.email])
```

- [ ] **Step 5: Add the bell row**

In `payments/notifications.py`, after `payment_reminder_inapp`:

```python
def installment_reminder_inapp(installment) -> None:
    """Bell row for a due payment-plan installment (task #501). The cron paces
    the email itself, gated by :func:`should_email`."""
    reg = installment.registration
    notify(
        reg.user, Category.REGISTRATION_STATUS,
        title=(
            f"Payment {installment.sequence} of your plan for "
            f"{reg.event.title} is due"
        ),
        url=_confirm_url(reg), target=installment, email=False, dedupe=True,
    )
```

- [ ] **Step 6: Add the third reminder kind**

In `payments/management/commands/send_registration_reminders.py`, after the
student-payment block and before the summary line:

```python
        # --- Payment-plan installment reminders (task #501) ---
        from payments import registration_plans
        from payments.emails import send_installment_reminder

        today = timezone.localdate()
        on_plan = (
            Registration.objects.filter(
                status=Registration.Status.PAID,
                installments__paid=False,
            )
            .filter(user__is_active=True)
            .exclude(user__profile__standing__in=Profile.NON_MEMBER_STANDINGS)
            .filter(due)
            .select_related("event", "user")
            .distinct()
        )
        installment_sent = 0
        for reg in on_plan:
            installment = registration_plans.due_installment(reg, today)
            if installment is None:
                continue
            if dry:
                self.stdout.write(
                    f"  would remind {reg.user.email} of payment "
                    f"{installment.sequence} for '{reg.event.title}'"
                )
            else:
                notify_payments.installment_reminder_inapp(installment)
                if notify_payments.should_email(reg.user, Category.REGISTRATION_STATUS):
                    sender.send(send_installment_reminder, installment)
                reg.reminded_at = timezone.now()
                reg.save(update_fields=["reminded_at"])
            installment_sent += 1
```

and extend the summary:

```python
        verb = "Would send" if dry else "Sent"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {faculty_sent} faculty approval reminder(s), "
            f"{student_sent} student payment reminder(s), and "
            f"{installment_sent} payment-plan reminder(s)."
        ))
```

Update the module docstring to list three kinds instead of two.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest payments/test_registration_plans.py payments/test_registration_reminders.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add payments/emails.py payments/notifications.py payments/templates/payments/email/installment_reminder.txt payments/management/commands/send_registration_reminders.py payments/test_registration_plans.py
git commit -m "feat(payments): nudge overdue registration-plan installments (task #501)"
```

---

### Task 9: Faculty and treasurer surfaces

**Files:**
- Modify: `events/forms.py:84-127` (`PricingCodeForm`)
- Modify: `registrations/models.py` (`on_payment_plan` property)
- Modify: `events/templates/events/_faculty_tools.html:49-121`
- Modify: `events/views.py:294-296` (roster prefetch)
- Modify: `workgroups/views.py:379-381` (roster prefetch)
- Modify: `payments/templates/payments/treasurer/member_detail.html:428-450`
- Test: `payments/test_registration_plans.py`

**Interfaces:**
- Consumes: Tasks 1 and 3.
- Produces: `registrations.models.Registration.on_payment_plan: bool` (property).

**Important:** `events/_faculty_tools.html` is included by **two** surfaces —
`events/templates/events/event_detail.html:55` and
`workgroups/templates/workgroups/detail.html:116`. For a seminar or reading
group the event page **redirects to the Workspace**
(`events/views.py:271`), so the roster faculty actually use is the Workspace's
`?tab=roster`. Both context builders need the prefetch; the template is shared,
so it changes once.

- [ ] **Step 1: Write the failing tests**

Append to `payments/test_registration_plans.py`:

```python
def test_the_mint_form_accepts_a_plan_without_a_discount():
    from events.forms import PricingCodeForm
    form = PricingCodeForm(data={
        "pricing_mode": PricingCode.Mode.FULL_PRICE,
        "installments": "3",
    })
    assert form.is_valid(), form.errors
    code = form.save(commit=False)
    assert code.installments == 3
    assert code.amount_or_percent == Decimal("0")


def test_the_mint_form_still_defaults_to_pay_in_full():
    """The new field must not become required — an existing POST omitting it
    still works (see the new-modelform-field-is-required-by-default memory)."""
    from events.forms import PricingCodeForm
    form = PricingCodeForm(data={
        "pricing_mode": PricingCode.Mode.PERCENT_OFF,
        "amount_or_percent": "20",
    })
    assert form.is_valid(), form.errors
    assert form.save(commit=False).installments == 1


def test_a_discount_mode_still_requires_an_amount():
    from events.forms import PricingCodeForm
    form = PricingCodeForm(data={"pricing_mode": PricingCode.Mode.FIXED_AMOUNT})
    assert not form.is_valid()
    assert "amount_or_percent" in form.errors


def test_the_faculty_roster_flags_a_plan_without_dollars(client):
    """The roster faculty actually use is the Workspace tab — a seminar's
    event page redirects there."""
    from payments import registration_plans
    from registrations.models import Registration
    faculty = _user("faculty@example.com")
    faculty.profile.is_faculty = True
    faculty.profile.save()
    member = _user()
    event = _event()
    event.add_faculty(faculty)
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    registration_plans.build_schedule(reg, 3, today=timezone.localdate())

    client.force_login(faculty)
    resp = client.get(event.workgroup.get_absolute_url() + "?tab=roster")
    body = resp.content.decode()
    assert "On a plan" in body
    assert "$100.00" not in body       # no per-installment dollars
    assert "2 of 3" not in body        # no progress


def test_a_registration_without_a_plan_is_not_flagged(client):
    from registrations.models import Registration
    faculty = _user("faculty@example.com")
    faculty.profile.is_faculty = True
    faculty.profile.save()
    member = _user()
    event = _event()
    event.add_faculty(faculty)
    tier = _tier(event)
    _registration(member, event, tier, "300.00", status=Registration.Status.PAID)

    client.force_login(faculty)
    resp = client.get(event.workgroup.get_absolute_url() + "?tab=roster")
    assert "On a plan" not in resp.content.decode()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest payments/test_registration_plans.py -k "mint_form or faculty_roster or discount_mode" -v`
Expected: FAIL — the form has no `installments` field; the roster has no chip.

- [ ] **Step 3: Extend the mint form**

In `events/forms.py`, `PricingCodeForm`:

Add `"installments"` to `Meta.fields`, positioned right after
`"amount_or_percent"`.

In `__init__`, after the existing `restricted_to_user` block:

```python
        # Adding a field with a model default silently makes it *required* on
        # an existing ModelForm, which would break every POST that omits it
        # (the new-modelform-field-is-required-by-default memory). Both of
        # these are optional on the form and coerced in clean.
        self.fields["installments"].required = False
        self.fields["installments"].label = "Number of payments"
        self.fields["installments"].help_text = (
            "Leave at 1 for the usual single payment. Choose more and the fee "
            "is split evenly, the first payment due at registration and the "
            "rest monthly. The total is the same either way."
        )
        self.fields["amount_or_percent"].required = False
```

Add the coercions and tighten `clean`:

```python
    def clean_installments(self):
        value = self.cleaned_data.get("installments")
        return value or 1

    def clean(self):
        data = super().clean()
        mode = data.get("pricing_mode")
        amount = data.get("amount_or_percent")

        if mode == PricingCode.Mode.FULL_PRICE:
            # No discount to state — the code exists to carry the schedule.
            data["amount_or_percent"] = self.instance.amount_or_percent = Decimal("0")
            return data

        if amount is None:
            self.add_error("amount_or_percent", "This field is required.")
            return data
        if mode == PricingCode.Mode.PERCENT_OFF and not (
            Decimal("0") <= amount <= Decimal("100")
        ):
            self.add_error("amount_or_percent", "percent_off requires a value between 0 and 100.")
        if amount < 0:
            self.add_error("amount_or_percent", "Cannot be negative.")
        return data
```

- [ ] **Step 4: Flag plans on the roster and the code list**

In `registrations/models.py`, add a property to `Registration` beside
`needs_payment`:

```python
    @property
    def on_payment_plan(self) -> bool:
        """Whether this registration is being paid in installments (task
        #501). A property so the two roster surfaces share one answer rather
        than each annotating their own queryset."""
        from payments.registration_plans import is_on_plan
        return is_on_plan(self)
```

In `events/views.py`, add the prefetch to the faculty-view roster queryset:

```python
        context["registrations"] = event.registrations.select_related(
            "user", "price_tier"
        ).prefetch_related("installments").order_by("created_at")
```

In `workgroups/views.py`, the same on the Roster tab's queryset:

```python
        context["registrations"] = primary_event.registrations.select_related(
            "user", "price_tier"
        ).prefetch_related("installments").order_by("created_at")
```

In `events/templates/events/_faculty_tools.html`, in the roster table's status
cell, after the status badge:

```html
              {% if reg.on_payment_plan %}
              <span class="badge badge-sm badge-ghost ml-1">On a plan</span>
              {% endif %}
```

In the existing-codes table, add a `Payments` header after `Value`:

```html
          <tr><th>Code</th><th>Mode</th><th>Value</th><th>Payments</th><th>Uses left</th><th>Expires</th><th>For</th></tr>
```

and the matching cell after the value cell:

```html
            <td class="whitespace-nowrap">{% if code.installments > 1 %}{{ code.installments }}{% else %}—{% endif %}</td>
```

- [ ] **Step 5: Note the plan on the treasurer's registrations table**

In `payments/templates/payments/treasurer/member_detail.html`, in the Event
registrations table, change the Quoted cell to:

```html
            <td class="whitespace-nowrap">
              ${{ r.quoted_amount }}
              {% if r.installments.exists %}
              <div class="text-xs text-base-content/60">
                payment plan, {{ r.installments.count }} payments
              </div>
              {% endif %}
            </td>
```

- [ ] **Step 6: Run the full suite and the linter**

Run: `uv run pytest -x -q`
Expected: PASS, all of it.

Run: `uv run ruff check .`
Expected: clean.

- [ ] **Step 7: Rebuild the CSS and check the new classes survive**

Run: `npm run build:css`
Expected: succeeds. The new utility classes (`btn-xs`, `badge-ghost`, `ml-1`)
all appear in templates, so Tailwind will keep them.

- [ ] **Step 8: Commit**

```bash
git add events/forms.py events/views.py workgroups/views.py registrations/models.py events/templates/events/_faculty_tools.html payments/templates/payments/treasurer/member_detail.html payments/test_registration_plans.py
git commit -m "feat(events): mint a payment-plan code; flag plans on rosters (task #501)"
```

---

## Post-implementation

- [ ] Update `CLAUDE.md`'s status list with a task #501 entry, in the style of
      the #485 and #486 entries: what changed, what was rejected, and the
      `PAID` semantic shift.
- [ ] Add a **project memory** via the projects connector
      (`project_slug="lsp-management"`): name
      `registration-payment-plans`, kind `architecture`, recording that a
      pricing code's `installments` is orthogonal to `pricing_mode`, that a
      plan registration is `PAID` (enrolled) while still owing, and that the
      ledger, not the registration status, is the truth about the money.
- [ ] Add a section to the faculty guide (`core/docs/faculty-guide.md`)
      explaining when to mint a plan code. **Watch the rendered-markdown
      gotcha:** a `+`, `-`, or `*` starting a wrapped line inside a list item
      silently becomes a nested bullet.
- [ ] Update `set_task_next_action` / `write_task_briefing` on task #501.

## Deployment notes

- Two migrations, both additive. No backfill, no data migration.
- No new environment variables, no new host timer — the installment reminder
  rides the existing `lsp-registration-reminders.timer`.
- **Deploy is not complete until the GitHub Actions Deploy run goes green** —
  a single failing test silently aborts it (the `pushed-is-not-deployed`
  gotcha).
