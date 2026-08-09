# Program-event pricing and visibility cascade — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an annual-program event's visibility actually cascade from its Program everywhere, and give the PC and faculty a way to set an event's price without Django admin.

**Architecture:** Three layers. (1) Every gate that reads the raw `Event.published` boolean moves to `Event.is_public_now` (instance sites) or a new `Event.public_now_q()` built on the never-called `Program.public_program_year_q()` (queryset sites). (2) A new `events/price_spec.py` holds one definition of "a price" — the four values the proposal form already collects — with `from_event` / `apply_to_event` / `label`; `EventProposal._build_price_tier` is refactored onto it so the two creation paths cannot drift. (3) `EventChangeRequest` carries a price change in two JSON columns, so a faculty price edit routes through the existing certify-or-submit dialog.

**Tech Stack:** Django 5.2, pytest-django, Tailwind v4 + DaisyUI v5, uv.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-09-program-event-pricing-and-cascade-design.md`. Read it before starting.
- **Vocabulary:** reuse the app's existing `fee_type` — **Free / Fixed amount / Sliding scale** (`events/forms.py:307`) plus `tuition_covers`. Do NOT introduce `mint_program_tiers`' fixed/donation/per-session names.
- **Safety property 1:** the price spec addresses only the event-level `audience=ALL` tier. An event with more than one tier, or any tier carrying a `session` FK, is **unrepresentable** — read-only in the UI, and `apply_to_event` raises rather than reconciling. Never silently drop a second tier.
- **Safety property 2:** a price change never touches `Registration.quoted_amount`. No retroactive re-quoting, ever.
- **`EventProposal.approve()` behaviour must not change.** `events/test_event_proposal.py` must stay green **without being edited**.
- **DaisyUI semantic tokens only** (`bg-base-100`, `text-base-content`, …), never `bg-gray-100`.
- **Tailwind scans templates only** — any class set in Python must also appear in a `.html` file.
- **Django template comments `{# #}` are single-line.** `core/test_templates.py` enforces this.
- Run `uv run pytest` and `uv run ruff check .` before every commit.

---

### Task 1: Cascade fix — instance sites

The five places that hold an `Event` and ask whether it is public.

**Files:**
- Modify: `events/models.py:577` (`registration_badge`)
- Modify: `registrations/views.py:151` (register gate)
- Modify: `events/templates/events/_event_summary.html:228`
- Modify: `events/templates/events/_location.html:60`
- Modify: `events/templates/events/event_detail.html:53`
- Test: `events/test_program_cascade.py` (create)

**Interfaces:**
- Consumes: `Event.is_public_now` (existing property, `events/models.py:632`).
- Produces: nothing new. Later tasks are independent of this one.

- [ ] **Step 1: Write the failing test**

Create `events/test_program_cascade.py`:

```python
"""The visibility cascade for annual-program events (task #532).

A seminar / reading group / cartel is public when its Program is public —
its own ``published`` flag is not the lever. See
docs/superpowers/specs/2026-08-09-program-event-pricing-and-cascade-design.md
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.urls import reverse

from events.models import Audience, Event, PriceTier, Program

pytestmark = pytest.mark.django_db


def _program_event(*, program_published=True, event_published=False,
                   event_type=Event.Type.SEMINAR, slug="cascade-seminar"):
    program = Program.objects.create(
        academic_year="2026-2027", published=program_published,
    )
    today = dt.date.today()
    event = Event.objects.create(
        title="Cascade Seminar", slug=slug, event_type=event_type,
        program=program, start_date=today + dt.timedelta(days=7),
        end_date=today + dt.timedelta(days=90),
        status=Event.Status.OPEN, published=event_published,
    )
    PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("100"),
        minimum_amount=Decimal("0"),
    )
    return event


def test_badge_follows_the_program_not_the_event_flag():
    event = _program_event(program_published=True, event_published=False)
    assert event.registration_badge["label"] == "Registration open"


def test_badge_reads_draft_when_the_program_is_unpublished():
    event = _program_event(program_published=False, event_published=False)
    assert event.registration_badge["label"] == "Draft"


def test_non_program_event_still_reads_its_own_flag():
    """A special event has no Program; ``published`` remains its lever."""
    today = dt.date.today()
    event = Event.objects.create(
        title="Special", slug="special-cascade",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=today + dt.timedelta(days=7),
        end_date=today + dt.timedelta(days=7),
        status=Event.Status.OPEN, published=False,
    )
    assert event.registration_badge["label"] == "Draft"
    event.published = True
    assert event.registration_badge["label"] == "Registration open"


def test_annual_type_without_a_program_falls_back_to_published():
    today = dt.date.today()
    event = Event.objects.create(
        title="Orphan", slug="orphan-cascade", event_type=Event.Type.SEMINAR,
        program=None, start_date=today + dt.timedelta(days=7),
        end_date=today + dt.timedelta(days=90),
        status=Event.Status.OPEN, published=True,
    )
    assert event.registration_badge["label"] == "Registration open"


def test_register_view_reachable_for_a_published_programs_event(client, django_user_model):
    event = _program_event(program_published=True, event_published=False)
    user = django_user_model.objects.create_user(
        email="member@example.com", password="pw",
    )
    client.force_login(user)
    response = client.get(reverse("registrations:register", args=[event.slug]))
    assert response.status_code == 200


def test_register_view_404s_when_the_program_is_unpublished(client, django_user_model):
    event = _program_event(program_published=False, event_published=False)
    user = django_user_model.objects.create_user(
        email="member2@example.com", password="pw",
    )
    client.force_login(user)
    response = client.get(reverse("registrations:register", args=[event.slug]))
    assert response.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest events/test_program_cascade.py -v`
Expected: `test_badge_follows_the_program_not_the_event_flag` FAILS (gets "Draft"), and `test_register_view_reachable_for_a_published_programs_event` FAILS with 404. The other four already pass.

- [ ] **Step 3: Fix `registration_badge`**

In `events/models.py`, in `registration_badge`, change the first guard:

```python
        if not self.is_public_now:
            return {"label": "Draft", "css": "badge-warning"}
```

- [ ] **Step 4: Fix the register gate**

In `registrations/views.py`, in `register_for_event`:

```python
    if not (event.is_public_now and event.status == Event.Status.OPEN):
        raise Http404("Registration not open for this event.")
```

- [ ] **Step 5: Fix the three templates**

`events/templates/events/_event_summary.html` line 228:

```html
  {% if event.status == "open" and event.is_public_now %}
```

`events/templates/events/_location.html` line 60:

```html
      {% if event.status == "open" and event.is_public_now %}
```

`events/templates/events/event_detail.html` line 53:

```html
      {% if not event.is_public_now %}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest events/test_program_cascade.py -v`
Expected: all 6 PASS.

- [ ] **Step 7: Run the full suite and lint**

Run: `uv run pytest && uv run ruff check .`
Expected: all green. If `events/test_seminar_workspace.py::test_registration_badge_states` fails, read it — it builds an event with no Program, so it should still pass via the fallback. Fix the test only if it asserts the *old* semantics for a program-owned event.

- [ ] **Step 8: Commit**

```bash
git add events/models.py registrations/views.py events/templates/events/_event_summary.html events/templates/events/_location.html events/templates/events/event_detail.html events/test_program_cascade.py
git commit -m "fix(events): the badge and register gate follow the program cascade (task #532)"
```

---

### Task 2: Cascade fix — queryset sites

The three querysets that filter on `published=True` and so hide a live program event.

**Files:**
- Modify: `events/models.py` (add `Event.public_now_q()`)
- Modify: `events/upcoming.py:40`
- Modify: `core/views.py:162`
- Modify: `events/views.py:137`
- Test: `events/test_program_cascade.py` (append)

**Interfaces:**
- Consumes: `Program.public_program_year_q()` (existing, `events/models.py:136`, currently uncalled).
- Produces: `Event.public_now_q() -> django.db.models.Q` — a classmethod matching exactly the rows for which `is_public_now` is True. Callers use it as `Event.objects.filter(Event.public_now_q())` or, for a related lookup, prefix the field names (`core/views.py` filters `Session` on `event__…`, so it needs the related form — see Step 5).

- [ ] **Step 1: Write the failing test**

Append to `events/test_program_cascade.py`:

```python
def test_public_now_q_matches_the_property_row_for_row():
    """The Q expression and the property must never disagree."""
    _program_event(program_published=True, event_published=False,
                   slug="q-live")
    _program_event(program_published=False, event_published=False,
                   slug="q-hidden")
    today = dt.date.today()
    Event.objects.create(
        title="Special", slug="q-special", event_type=Event.Type.SPECIAL_EVENT,
        start_date=today, end_date=today, published=True,
    )
    Event.objects.create(
        title="Orphan", slug="q-orphan", event_type=Event.Type.SEMINAR,
        program=None, start_date=today, end_date=today, published=True,
    )
    matched = set(
        Event.objects.filter(Event.public_now_q()).values_list("slug", flat=True)
    )
    expected = {e.slug for e in Event.objects.all() if e.is_public_now}
    assert matched == expected
    assert "q-live" in matched
    assert "q-hidden" not in matched


def test_landing_list_includes_a_program_event_with_published_false():
    from events.upcoming import landing_events
    event = _program_event(program_published=True, event_published=False,
                           slug="landing-cascade")
    assert event.slug in [e.slug for e in landing_events(None, limit=50)]


def test_calendar_feed_includes_a_program_events_sessions(client):
    from django.utils import timezone
    from events.models import Session
    event = _program_event(program_published=True, event_published=False,
                           slug="calendar-cascade")
    start = timezone.now() + dt.timedelta(days=10)
    Session.objects.create(
        event=event, start_at=start, end_at=start + dt.timedelta(hours=2),
        sequence=1,
    )
    response = client.get(reverse("calendar_events_json"))
    assert response.status_code == 200
    assert "Cascade Seminar" in response.content.decode()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest events/test_program_cascade.py -v -k "q_matches or landing or calendar"`
Expected: FAIL — `AttributeError: type object 'Event' has no attribute 'public_now_q'` for the first, and missing rows for the other two.

If `reverse("calendar_events_json")` raises `NoReverseMatch`, find the real name with `grep -rn "events.json" core/urls.py config/urls.py` and use that; do not delete the test.

- [ ] **Step 3: Add `Event.public_now_q()`**

In `events/models.py`, on `Event`, next to `is_public_now`:

```python
    @classmethod
    def public_now_q(cls, prefix: str = "") -> "models.Q":
        """Q expression selecting exactly the rows where ``is_public_now`` is True.

        The queryset counterpart of that property — annual-program types
        cascade from their Program, everything else reads ``published``.
        ``prefix`` lets a related queryset filter through a FK
        (``Session.objects.filter(Event.public_now_q("event__"))``).
        """
        from django.db.models import Q
        from django.utils import timezone

        annual = Q(**{f"{prefix}event_type__in": list(cls.ANNUAL_PROGRAM_TYPES)})
        has_program = Q(**{f"{prefix}program__isnull": False})
        published = Q(**{f"{prefix}published": True})
        program_public = (
            Q(**{f"{prefix}program__published": True})
            | Q(**{f"{prefix}program__publish_date__lte": timezone.now()})
        )
        return (
            (annual & has_program & program_public)
            | (annual & ~has_program & published)
            | (~annual & published)
        )
```

Note this inlines what `Program.public_program_year_q()` expresses, because that helper hardcodes the `program__` prefix and cannot serve the `event__program__` case. Delete `Program.public_program_year_q` in Step 6 — it has no callers and keeping a second, less capable spelling is how this bug happened.

- [ ] **Step 4: Use it in the three querysets**

`events/upcoming.py`, in `_base_queryset` — replace `Event.objects.filter(published=True)`:

```python
    qs = Event.objects.filter(Event.public_now_q()).filter(
```

`events/views.py` line 137 — replace `Event.objects.filter(published=True, end_date__gte=today)`:

```python
        Event.objects.filter(Event.public_now_q(), end_date__gte=today)
```

`core/views.py` line 162 — replace `qs = qs.filter(event__published=True)`:

```python
        from events.models import Event
        qs = qs.filter(Event.public_now_q("event__"))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest events/test_program_cascade.py -v`
Expected: all 9 PASS.

- [ ] **Step 6: Delete the superseded helper**

Remove `Program.public_program_year_q` from `events/models.py` (lines ~135-140). Confirm it has no callers first:

Run: `grep -rn "public_program_year_q" --include=*.py . | grep -v .claude-worktrees`
Expected: only the definition. If anything else appears, keep the method and have it delegate to `Event.public_now_q()` instead.

- [ ] **Step 7: Run the full suite and lint**

Run: `uv run pytest && uv run ruff check .`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add events/models.py events/upcoming.py events/views.py core/views.py events/test_program_cascade.py
git commit -m "fix(events): program events appear in listings, calendar and landing (task #532)"
```

---

### Task 3: `events/price_spec.py`

One definition of a price, shared by every surface.

**Files:**
- Create: `events/price_spec.py`
- Create: `events/test_price_spec.py`
- Modify: `events/models.py` (`EventProposal._build_price_tier`)

**Interfaces:**
- Consumes: `PriceTier`, `Audience` from `events.models`.
- Produces:
  - `PriceSpec` — frozen dataclass with `amount: Decimal | None`, `sliding_min: Decimal | None`, `sliding_max: Decimal | None`, `tuition_covers: bool`; derived property `fee_type -> "free" | "fixed" | "sliding"`; `to_dict() -> dict`; classmethod `from_dict(dict) -> PriceSpec`.
  - `UnrepresentablePricing(Exception)`
  - `is_representable(event) -> bool`
  - `from_event(event) -> PriceSpec | None` (None when unrepresentable)
  - `apply_to_event(event, spec) -> None` (raises `UnrepresentablePricing`)
  - `label(spec) -> str`

- [ ] **Step 1: Write the failing test**

Create `events/test_price_spec.py`:

```python
"""One shared definition of an event's price (task #532)."""
import datetime as dt
from decimal import Decimal

import pytest

from events.models import Audience, Event, PriceTier, Session
from events.price_spec import (
    PriceSpec,
    UnrepresentablePricing,
    apply_to_event,
    from_event,
    is_representable,
    label,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def event():
    today = dt.date.today()
    return Event.objects.create(
        title="Priced", slug="priced-event", event_type=Event.Type.SEMINAR,
        start_date=today, end_date=today + dt.timedelta(days=30),
    )


def test_fee_type_is_derived_from_the_amounts():
    assert PriceSpec().fee_type == "free"
    assert PriceSpec(amount=Decimal("500")).fee_type == "fixed"
    assert PriceSpec(sliding_max=Decimal("100")).fee_type == "sliding"
    assert PriceSpec(sliding_min=Decimal("0")).fee_type == "sliding"


@pytest.mark.parametrize("spec", [
    PriceSpec(amount=Decimal("500"), tuition_covers=True),
    PriceSpec(amount=Decimal("50"), tuition_covers=False),
    PriceSpec(sliding_min=Decimal("0"), sliding_max=Decimal("100")),
    PriceSpec(tuition_covers=True),
])
def test_round_trips_through_the_event(event, spec):
    apply_to_event(event, spec)
    assert from_event(event) == spec


@pytest.mark.parametrize("spec", [
    PriceSpec(amount=Decimal("500"), tuition_covers=True),
    PriceSpec(sliding_min=Decimal("0"), sliding_max=Decimal("100")),
])
def test_round_trips_through_json(spec):
    assert PriceSpec.from_dict(spec.to_dict()) == spec


def test_applying_twice_leaves_one_tier(event):
    apply_to_event(event, PriceSpec(amount=Decimal("500")))
    apply_to_event(event, PriceSpec(amount=Decimal("400")))
    assert event.price_tiers.count() == 1
    assert event.price_tiers.get().base_amount == Decimal("400")


def test_free_and_uncovered_creates_no_tier(event):
    """Matches _build_price_tier's 'nothing specified' short-circuit."""
    apply_to_event(event, PriceSpec(tuition_covers=False))
    assert event.price_tiers.count() == 0
    assert from_event(event) == PriceSpec(tuition_covers=False)


def test_a_second_tier_makes_the_event_unrepresentable(event):
    PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("500"),
        minimum_amount=Decimal("0"),
    )
    PriceTier.objects.create(
        event=event, audience=Audience.STUDENT, base_amount=Decimal("300"),
        minimum_amount=Decimal("0"),
    )
    assert is_representable(event) is False
    assert from_event(event) is None
    with pytest.raises(UnrepresentablePricing):
        apply_to_event(event, PriceSpec(amount=Decimal("100")))
    assert event.price_tiers.count() == 2  # nothing was dropped


def test_a_session_scoped_tier_makes_the_event_unrepresentable(event):
    from django.utils import timezone
    session = Session.objects.create(
        event=event, start_at=timezone.now(),
        end_at=timezone.now() + dt.timedelta(hours=2), sequence=1,
    )
    PriceTier.objects.create(
        event=event, session=session, audience=Audience.ALL,
        base_amount=Decimal("60"), minimum_amount=Decimal("0"),
    )
    assert is_representable(event) is False
    with pytest.raises(UnrepresentablePricing):
        apply_to_event(event, PriceSpec(amount=Decimal("100")))


def test_labels():
    assert label(PriceSpec(amount=Decimal("500"), tuition_covers=True)) == (
        "$500, covered by School tuition"
    )
    assert label(PriceSpec(amount=Decimal("50"), tuition_covers=False)) == "$50"
    assert label(PriceSpec(sliding_min=Decimal("0"), sliding_max=Decimal("100"),
                           tuition_covers=False)) == "Sliding scale $0 to $100"
    assert label(PriceSpec(tuition_covers=False)) == "Free"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest events/test_price_spec.py -v`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'events.price_spec'`.

- [ ] **Step 3: Write the module**

Create `events/price_spec.py`:

```python
"""One definition of an event's price (task #532).

The proposal form has always described a price with four values — a fixed
amount, a sliding floor and ceiling, and whether tuition covers it. This
module lifts that description out of the form so the PC's event form, the
faculty edit form, and the change-review loop share it, and so the two
event-creation paths cannot drift apart again.

**Scope, deliberately narrow.** A spec describes the event-level
``audience=ALL`` tier and nothing else. An event carrying a second tier (a
student rate) or a session-scoped tier is *unrepresentable*: reading it
returns ``None`` and writing it raises, rather than reconciling the extra
rows away. Django admin remains the surface for those.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


class UnrepresentablePricing(Exception):
    """The event's tiers are richer than a spec can describe."""


def _dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


@dataclass(frozen=True)
class PriceSpec:
    """What an event costs. ``fee_type`` is derived, never stored."""

    amount: Decimal | None = None
    sliding_min: Decimal | None = None
    sliding_max: Decimal | None = None
    tuition_covers: bool = True

    @property
    def fee_type(self) -> str:
        if self.sliding_min is not None or self.sliding_max is not None:
            return "sliding"
        if self.amount is not None:
            return "fixed"
        return "free"

    def to_dict(self) -> dict:
        """JSON-safe form (Decimals as strings) for EventChangeRequest."""
        return {
            "amount": None if self.amount is None else str(self.amount),
            "sliding_min": None if self.sliding_min is None else str(self.sliding_min),
            "sliding_max": None if self.sliding_max is None else str(self.sliding_max),
            "tuition_covers": self.tuition_covers,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "PriceSpec":
        data = data or {}
        return cls(
            amount=_dec(data.get("amount")),
            sliding_min=_dec(data.get("sliding_min")),
            sliding_max=_dec(data.get("sliding_max")),
            tuition_covers=bool(data.get("tuition_covers", True)),
        )


def _event_level_tiers(event):
    return list(event.price_tiers.all())


def is_representable(event) -> bool:
    """True when a spec can describe this event's pricing without loss."""
    tiers = _event_level_tiers(event)
    if len(tiers) > 1:
        return False
    if not tiers:
        return True
    tier = tiers[0]
    from .models import Audience
    return tier.session_id is None and tier.audience == Audience.ALL


def from_event(event) -> PriceSpec | None:
    """The event's current price, or None when it is unrepresentable."""
    if not is_representable(event):
        return None
    tier = event.price_tiers.first()
    if tier is None:
        return PriceSpec(tuition_covers=False)
    if tier.sliding_scale:
        return PriceSpec(
            sliding_min=tier.minimum_amount or Decimal("0"),
            sliding_max=tier.base_amount,
            tuition_covers=tier.covered_by_tuition,
        )
    if tier.base_amount == 0 and tier.covered_by_tuition:
        return PriceSpec(tuition_covers=True)
    return PriceSpec(
        amount=tier.base_amount, tuition_covers=tier.covered_by_tuition,
    )


def apply_to_event(event, spec: PriceSpec) -> None:
    """Reconcile the event's single event-level tier to ``spec``.

    Mirrors ``EventProposal._build_price_tier`` exactly, including its
    "nothing specified" short-circuit: a free event that tuition does not
    cover carries no tier at all.
    """
    if not is_representable(event):
        raise UnrepresentablePricing(
            f"{event.slug} carries pricing a spec cannot describe; "
            "edit its tiers in Django admin."
        )
    from .models import Audience, PriceTier

    sliding = spec.fee_type == "sliding"
    if not sliding and spec.amount is None and not spec.tuition_covers:
        event.price_tiers.all().delete()
        return

    base = spec.amount
    if base is None:
        base = spec.sliding_max if spec.sliding_max is not None else Decimal("0")

    values = {
        "audience": Audience.ALL,
        "base_amount": base,
        "sliding_scale": sliding,
        "minimum_amount": (spec.sliding_min or Decimal("0")) if sliding else Decimal("0"),
        "covered_by_tuition": spec.tuition_covers,
    }
    tier = event.price_tiers.first()
    if tier is None:
        PriceTier.objects.create(event=event, **values)
    else:
        for field, value in values.items():
            setattr(tier, field, value)
        tier.save(update_fields=list(values))


def _money(value: Decimal) -> str:
    """'$500' for whole dollars, '$62.50' otherwise."""
    value = Decimal(value)
    if value == value.to_integral_value():
        return f"${value.to_integral_value()}"
    return f"${value:.2f}"


def label(spec: PriceSpec) -> str:
    """A short human description, for the review diff and admin listings."""
    if spec.fee_type == "sliding":
        low = _money(spec.sliding_min or Decimal("0"))
        high = _money(spec.sliding_max or Decimal("0"))
        base = f"Sliding scale {low} to {high}"
    elif spec.fee_type == "fixed":
        base = _money(spec.amount)
    else:
        base = "Free"
    if spec.tuition_covers:
        return f"{base}, covered by School tuition"
    return base
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest events/test_price_spec.py -v`
Expected: all PASS. If `test_round_trips_through_the_event[PriceSpec(amount=None...tuition_covers=True)]` fails, check `from_event`'s zero-and-covered branch — a free-but-covered event stores a `$0` covered tier and must read back as `PriceSpec(tuition_covers=True)`, not as `amount=0`.

- [ ] **Step 5: Refactor `_build_price_tier` onto it**

In `events/models.py`, replace the body of `EventProposal._build_price_tier`:

```python
    def _build_price_tier(self, event):
        """Create a PriceTier on the minted event from the proposed fee."""
        from .price_spec import PriceSpec, apply_to_event
        apply_to_event(event, PriceSpec(
            amount=self.fee_amount,
            sliding_min=self.fee_sliding_min,
            sliding_max=self.fee_sliding_max,
            tuition_covers=self.tuition_covers,
        ))
```

- [ ] **Step 6: Verify the proposal path is unchanged**

Run: `uv run pytest events/test_event_proposal.py -v`
Expected: all PASS, with **no edits to that file**. If any fail, `apply_to_event` diverges from the old `_build_price_tier` — fix `apply_to_event`, not the test.

- [ ] **Step 7: Run the full suite and lint**

Run: `uv run pytest && uv run ruff check .`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add events/price_spec.py events/test_price_spec.py events/models.py
git commit -m "feat(events): one shared price spec, used by proposal approval (task #532)"
```

---

### Task 4: The fee block on the PC's event form

**Files:**
- Modify: `events/forms.py` (add `PriceFieldsMixin`; mount on `ProgramEventForm`)
- Create: `events/templates/events/_price_fields.html`
- Modify: `events/templates/events/program_admin/event_form.html` (after the fee_note block, ~line 85)
- Test: `events/test_program_event_pricing.py` (create)

**Interfaces:**
- Consumes: `PriceSpec`, `from_event`, `apply_to_event`, `is_representable` from Task 3.
- Produces: `PriceFieldsMixin` — adds form fields `fee_type` (ChoiceField, RadioSelect, choices free/fixed/sliding), `fee_amount`, `fee_sliding_min`, `fee_sliding_max` (DecimalField, `required=False`), `tuition_covers` (BooleanField, `required=False`); sets `self.price_readonly: bool`; `clean()` puts a `PriceSpec` at `cleaned_data["price"]` (or `None` when read-only); `save_price(event)` applies it. Task 5 reuses this mixin on `EventEditForm`.

- [ ] **Step 1: Write the failing test**

Create `events/test_program_event_pricing.py`:

```python
"""The PC can set an event's price without Django admin (task #532)."""
import datetime as dt
from decimal import Decimal

import pytest

from events.models import Audience, Event, PriceTier, Program
from events.price_spec import PriceSpec, from_event

pytestmark = pytest.mark.django_db


@pytest.fixture
def program():
    return Program.objects.create(academic_year="2026-2027", published=True)


def _post_data(**overrides):
    today = dt.date.today()
    data = {
        "title": "New Seminar", "slug": "new-seminar",
        "event_type": Event.Type.SEMINAR,
        "start_date": today.isoformat(),
        "end_date": (today + dt.timedelta(days=90)).isoformat(),
        "format": Event.Format.ONLINE, "status": Event.Status.OPEN,
        "description": "", "readings": "", "schedule_note": "",
        "contact": "", "fee_note": "", "access_info": "",
        "fee_type": "fixed", "fee_amount": "500", "tuition_covers": "on",
    }
    data.update(overrides)
    return data


def test_creating_an_event_mints_its_price_tier(program):
    from events.forms import ProgramEventForm
    form = ProgramEventForm(_post_data(), program=program)
    assert form.is_valid(), form.errors
    event = form.save()
    form.save_price(event)
    assert from_event(event) == PriceSpec(
        amount=Decimal("500"), tuition_covers=True,
    )


def test_sliding_scale_round_trips(program):
    from events.forms import ProgramEventForm
    form = ProgramEventForm(
        _post_data(fee_type="sliding", fee_amount="",
                   fee_sliding_min="0", fee_sliding_max="100"),
        program=program,
    )
    assert form.is_valid(), form.errors
    event = form.save()
    form.save_price(event)
    assert from_event(event) == PriceSpec(
        sliding_min=Decimal("0"), sliding_max=Decimal("100"),
        tuition_covers=True,
    )


def test_a_fixed_fee_needs_an_amount(program):
    from events.forms import ProgramEventForm
    form = ProgramEventForm(
        _post_data(fee_type="fixed", fee_amount=""), program=program,
    )
    assert not form.is_valid()
    assert "fee_amount" in form.errors


def test_sliding_minimum_cannot_exceed_the_maximum(program):
    from events.forms import ProgramEventForm
    form = ProgramEventForm(
        _post_data(fee_type="sliding", fee_amount="",
                   fee_sliding_min="200", fee_sliding_max="100"),
        program=program,
    )
    assert not form.is_valid()
    assert "fee_sliding_min" in form.errors


def test_editing_prefills_the_current_price(program):
    from events.forms import ProgramEventForm
    today = dt.date.today()
    event = Event.objects.create(
        title="Existing", slug="existing", event_type=Event.Type.SEMINAR,
        program=program, start_date=today, end_date=today,
    )
    PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("400"),
        minimum_amount=Decimal("0"), covered_by_tuition=True,
    )
    form = ProgramEventForm(instance=event, program=program)
    assert form.initial["fee_type"] == "fixed"
    assert form.initial["fee_amount"] == Decimal("400")
    assert form.initial["tuition_covers"] is True
    assert form.price_readonly is False


def test_a_multi_tier_event_renders_read_only(program):
    """Safety property 1: never offer an edit that would drop a tier."""
    from events.forms import ProgramEventForm
    today = dt.date.today()
    event = Event.objects.create(
        title="Two tiers", slug="two-tiers", event_type=Event.Type.SEMINAR,
        program=program, start_date=today, end_date=today,
    )
    for audience, amount in ((Audience.ALL, "600"), (Audience.STUDENT, "400")):
        PriceTier.objects.create(
            event=event, audience=audience, base_amount=Decimal(amount),
            minimum_amount=Decimal("0"),
        )
    form = ProgramEventForm(instance=event, program=program)
    assert form.price_readonly is True

    bound = ProgramEventForm(
        _post_data(title="Two tiers", slug="two-tiers", fee_amount="1"),
        instance=event, program=program,
    )
    assert bound.is_valid(), bound.errors
    saved = bound.save()
    bound.save_price(saved)
    assert saved.price_tiers.count() == 2
    assert set(saved.price_tiers.values_list("base_amount", flat=True)) == {
        Decimal("600"), Decimal("400"),
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest events/test_program_event_pricing.py -v`
Expected: FAIL — `AttributeError: 'ProgramEventForm' object has no attribute 'save_price'`.

- [ ] **Step 3: Write the mixin**

In `events/forms.py`, above `ProgramEventForm`:

```python
class PriceFieldsMixin(forms.Form):
    """The event-price inputs, shared by the PC form and the faculty form.

    Reuses the vocabulary the proposal form already established — Free /
    Fixed amount / Sliding scale plus "covered by tuition" — so the school
    has one way of describing a price. When the event's tiers are richer
    than a :class:`~events.price_spec.PriceSpec` can hold, the block goes
    read-only rather than offering a lossy edit (task #532).

    Inherits ``forms.Form`` deliberately: ``DeclarativeFieldsMetaclass``
    collects a base's fields via its ``declared_fields``, which a plain
    ``object`` mixin does not have — its fields would be silently dropped.
    """

    fee_type = forms.ChoiceField(
        required=False, label="Price",
        choices=[("free", "Free"), ("fixed", "Fixed amount"),
                 ("sliding", "Sliding scale")],
        widget=forms.RadioSelect, initial="free",
    )
    fee_amount = forms.DecimalField(
        required=False, max_digits=8, decimal_places=2, min_value=0,
        label="Amount",
        widget=forms.NumberInput(
            attrs={"class": "input input-bordered w-full", "step": "0.01"},
        ),
    )
    fee_sliding_min = forms.DecimalField(
        required=False, max_digits=8, decimal_places=2, min_value=0,
        label="Minimum (0 = none turned away)",
        widget=forms.NumberInput(
            attrs={"class": "input input-bordered w-full", "step": "0.01"},
        ),
    )
    fee_sliding_max = forms.DecimalField(
        required=False, max_digits=8, decimal_places=2, min_value=0,
        label="Suggested amount",
        widget=forms.NumberInput(
            attrs={"class": "input input-bordered w-full", "step": "0.01"},
        ),
    )
    tuition_covers = forms.BooleanField(
        required=False, initial=True, label="Covered by School tuition",
        widget=forms.CheckboxInput(attrs={"class": "checkbox checkbox-sm"}),
    )

    #: Fields the price block owns, for the read-only case and the mixin's clean.
    PRICE_FIELDS = (
        "fee_type", "fee_amount", "fee_sliding_min", "fee_sliding_max",
        "tuition_covers",
    )

    def init_price_fields(self, event):
        """Prefill from ``event`` and decide whether the block is editable.

        Call from ``__init__`` after ``super().__init__``.
        """
        from .price_spec import from_event, is_representable

        self.price_readonly = event is not None and not is_representable(event)
        if self.price_readonly:
            self.price_tiers = list(event.price_tiers.all())
            for name in self.PRICE_FIELDS:
                self.fields[name].disabled = True
            return
        self.price_tiers = []
        if event is None or self.is_bound:
            return
        spec = from_event(event)
        if spec is None:
            return
        self.initial.setdefault("fee_type", spec.fee_type)
        self.initial.setdefault("fee_amount", spec.amount)
        self.initial.setdefault("fee_sliding_min", spec.sliding_min)
        self.initial.setdefault("fee_sliding_max", spec.sliding_max)
        self.initial.setdefault("tuition_covers", spec.tuition_covers)

    def clean_price(self, data):
        """Normalize the price inputs into ``data["price"]``.

        Call from the concrete form's ``clean()``. Keeps only the inputs
        matching the chosen type, mirroring ``EventProposalForm.clean``.
        """
        from .price_spec import PriceSpec

        if getattr(self, "price_readonly", False):
            data["price"] = None
            return data

        fee_type = data.get("fee_type") or "free"
        amount = data.get("fee_amount")
        smin, smax = data.get("fee_sliding_min"), data.get("fee_sliding_max")

        if fee_type == "free":
            amount = smin = smax = None
        elif fee_type == "fixed":
            smin = smax = None
            if amount is None:
                self.add_error(
                    "fee_amount",
                    "Enter an amount, or choose Free / Sliding scale.",
                )
        else:
            amount = None
            if smax is None:
                self.add_error("fee_sliding_max", "Enter a suggested amount.")
            elif smin is not None and smin > smax:
                self.add_error(
                    "fee_sliding_min",
                    "Minimum can't exceed the suggested amount.",
                )

        data["price"] = PriceSpec(
            amount=amount, sliding_min=smin, sliding_max=smax,
            tuition_covers=bool(data.get("tuition_covers")),
        )
        return data

    def save_price(self, event):
        """Apply the cleaned price to ``event``. No-op when read-only."""
        from .price_spec import apply_to_event

        spec = (self.cleaned_data or {}).get("price")
        if spec is None:
            return
        apply_to_event(event, spec)
```

- [ ] **Step 4: Mount it on `ProgramEventForm`**

Change the class declaration and add the two hooks:

```python
class ProgramEventForm(PriceFieldsMixin, forms.ModelForm):
```

At the end of `ProgramEventForm.__init__`, after the existing setup:

```python
        self.init_price_fields(self.instance if self.instance.pk else None)
```

Add (or extend) `ProgramEventForm.clean`:

```python
    def clean(self):
        data = super().clean()
        return self.clean_price(data)
```

If `ProgramEventForm` already defines `clean`, append `return self.clean_price(data)` to it rather than adding a second method.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest events/test_program_event_pricing.py -v`
Expected: all 6 PASS.

- [ ] **Step 6: Save the price from the two PC views**

In `events/views.py`, `program_admin_event_new`, after `event = form.save()`:

```python
            event = form.save()
            form.save_price(event)
```

In `program_admin_event_edit`, replace the bare `form.save()`:

```python
            form.save_price(form.save())
```

- [ ] **Step 7: Add the template partial**

Create `events/templates/events/_price_fields.html`:

```html
{# Shared event-price block: PC event form + faculty edit form (task #532). #}
<div class="space-y-3" data-price-block>
  <span class="block text-xs uppercase tracking-wider text-base-content/60">Price</span>

  {% if form.price_readonly %}
  <div class="rounded-lg border border-base-300 bg-base-200/40 p-3 space-y-2">
    <p class="text-sm text-base-content/80">
      This event has more than one price, so it's edited in the site admin.
    </p>
    <ul class="text-sm text-base-content/70 space-y-1">
      {% for tier in form.price_tiers %}
      <li>{{ tier.get_audience_display }}, ${{ tier.base_amount }}{% if tier.sliding_scale %}, sliding from ${{ tier.minimum_amount }}{% endif %}{% if tier.covered_by_tuition %}, covered by tuition{% endif %}</li>
      {% endfor %}
    </ul>
  </div>
  {% else %}
  <div class="space-y-2">
    {% for choice in form.fee_type %}
    <label class="flex items-center gap-2 cursor-pointer text-sm">
      {{ choice.tag }} <span>{{ choice.choice_label }}</span>
    </label>
    {% endfor %}
  </div>

  <div data-price-fixed>
    <label for="{{ form.fee_amount.id_for_label }}" class="block text-xs text-base-content/60 mb-1">{{ form.fee_amount.label }}</label>
    {{ form.fee_amount }}
    {% if form.fee_amount.errors %}<p class="text-error text-xs mt-1">{{ form.fee_amount.errors|join:", " }}</p>{% endif %}
  </div>

  <div data-price-sliding class="grid grid-cols-2 gap-3">
    <div>
      <label for="{{ form.fee_sliding_min.id_for_label }}" class="block text-xs text-base-content/60 mb-1">{{ form.fee_sliding_min.label }}</label>
      {{ form.fee_sliding_min }}
      {% if form.fee_sliding_min.errors %}<p class="text-error text-xs mt-1">{{ form.fee_sliding_min.errors|join:", " }}</p>{% endif %}
    </div>
    <div>
      <label for="{{ form.fee_sliding_max.id_for_label }}" class="block text-xs text-base-content/60 mb-1">{{ form.fee_sliding_max.label }}</label>
      {{ form.fee_sliding_max }}
      {% if form.fee_sliding_max.errors %}<p class="text-error text-xs mt-1">{{ form.fee_sliding_max.errors|join:", " }}</p>{% endif %}
    </div>
  </div>

  <label class="flex items-center gap-2 cursor-pointer text-sm">
    {{ form.tuition_covers }} <span>{{ form.tuition_covers.label }}</span>
  </label>
  <p class="text-xs text-base-content/50">
    Faculty and conveners may set alternative rates or waive the fee for
    individual students who indicate financial need.
  </p>
  {% endif %}
</div>

<script>
  (function () {
    var block = document.querySelector("[data-price-block]");
    if (!block) return;
    var fixed = block.querySelector("[data-price-fixed]");
    var sliding = block.querySelector("[data-price-sliding]");
    if (!fixed || !sliding) return;
    function sync() {
      var checked = block.querySelector('input[name="fee_type"]:checked');
      var value = checked ? checked.value : "free";
      fixed.hidden = value !== "fixed";
      sliding.hidden = value !== "sliding";
    }
    block.addEventListener("change", function (event) {
      if (event.target.name === "fee_type") sync();
    });
    sync();
  })();
</script>
```

- [ ] **Step 8: Include it on the PC event form**

In `events/templates/events/program_admin/event_form.html`, immediately after the `fee_note` block (around line 85), add:

```html
        {% include "events/_price_fields.html" %}
```

- [ ] **Step 9: Verify in a browser**

Run: `npm run build:css` then `uv run python manage.py runserver`

Check `/admin-tools/program/2026-2027/events/<slug>/`: the radio switches which inputs show, an existing price prefills, and a multi-tier event shows the read-only panel. Fix any styling that reads as unthemed.

- [ ] **Step 10: Run the full suite and lint**

Run: `uv run pytest && uv run ruff check .`
Expected: all green. `core/test_templates.py` will fail if any `{# #}` comment spans two lines.

- [ ] **Step 11: Commit**

```bash
git add events/forms.py events/views.py events/templates/events/_price_fields.html events/templates/events/program_admin/event_form.html events/test_program_event_pricing.py
git commit -m "feat(events): the PC sets an event's price on the event form (task #532)"
```

---

### Task 5: Price as a reviewable field

**Files:**
- Modify: `events/models.py` (`EventChangeRequest`: two fields, `apply`, `field_changes`)
- Create: `events/migrations/00XX_changerequest_price.py` (generated)
- Modify: `events/review.py` (`REVIEWABLE_FIELDS`, `FIELD_LABELS`, `changed_reviewable_fields`)
- Modify: `events/forms.py` (`EventEditForm` gains the mixin)
- Modify: `events/views.py` (`event_edit` — build and apply the price change)
- Modify: `events/templates/events/event_edit.html` (include the partial)
- Modify: `events/templates/events/event_edit_confirm.html` (carry `tuition_covers` across the re-post)
- Test: `events/test_price_review.py` (create)

**Interfaces:**
- Consumes: `PriceFieldsMixin` (Task 4), `PriceSpec` / `apply_to_event` / `label` (Task 3).
- Produces: `EventChangeRequest.proposed_price` and `.original_price` (JSONField, null=True) holding `PriceSpec.to_dict()`; `"price"` as a member of `REVIEWABLE_FIELDS`.

- [ ] **Step 1: Write the failing test**

Create `events/test_price_review.py`:

```python
"""A faculty price change routes through PC review (task #532)."""
import datetime as dt
from decimal import Decimal

import pytest

from events.models import (
    Audience, Event, EventChangeRequest, EventProposal, PriceTier, Program,
)
from events.price_spec import PriceSpec, from_event

pytestmark = pytest.mark.django_db


@pytest.fixture
def approved_event(django_user_model):
    """A published seminar minted from an approved proposal — the only
    shape that requires_change_review() covers."""
    program = Program.objects.create(academic_year="2026-2027", published=True)
    faculty = django_user_model.objects.create_user(
        email="faculty@example.com", password="pw", is_staff=True,
    )
    today = dt.date.today()
    event = Event.objects.create(
        title="Reviewed", slug="reviewed-seminar",
        event_type=Event.Type.SEMINAR, program=program,
        start_date=today, end_date=today + dt.timedelta(days=90),
        published=True, status=Event.Status.OPEN,
    )
    PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("500"),
        minimum_amount=Decimal("0"), covered_by_tuition=True,
    )
    EventProposal.objects.create(
        title="Reviewed", event_type=Event.Type.SEMINAR,
        status=EventProposal.Status.APPROVED, minted_event=event,
        proposed_by=faculty,
    )
    return event, faculty


def test_price_is_a_reviewable_field():
    from events.review import FIELD_LABELS, REVIEWABLE_FIELDS
    assert "price" in REVIEWABLE_FIELDS
    assert FIELD_LABELS["price"] == "Price"


def test_a_pending_price_change_leaves_the_live_price_alone(approved_event):
    event, faculty = approved_event
    request = EventChangeRequest.objects.create(
        event=event, proposed_by=faculty,
        status=EventChangeRequest.Status.PENDING,
        changed_fields=["price"],
        original_price=PriceSpec(
            amount=Decimal("500"), tuition_covers=True).to_dict(),
        proposed_price=PriceSpec(
            amount=Decimal("300"), tuition_covers=True).to_dict(),
    )
    event.refresh_from_db()
    assert from_event(event).amount == Decimal("500")
    assert request.status == EventChangeRequest.Status.PENDING


def test_approving_applies_the_new_price(approved_event):
    event, faculty = approved_event
    request = EventChangeRequest.objects.create(
        event=event, proposed_by=faculty,
        status=EventChangeRequest.Status.PENDING,
        changed_fields=["price"],
        original_price=PriceSpec(
            amount=Decimal("500"), tuition_covers=True).to_dict(),
        proposed_price=PriceSpec(
            amount=Decimal("300"), tuition_covers=True).to_dict(),
    )
    request.approve(faculty)
    event.refresh_from_db()
    assert from_event(event) == PriceSpec(
        amount=Decimal("300"), tuition_covers=True,
    )
    assert request.status == EventChangeRequest.Status.APPROVED


def test_field_changes_renders_prices_as_labels(approved_event):
    event, faculty = approved_event
    request = EventChangeRequest.objects.create(
        event=event, proposed_by=faculty, changed_fields=["price"],
        original_price=PriceSpec(
            amount=Decimal("500"), tuition_covers=True).to_dict(),
        proposed_price=PriceSpec(
            amount=Decimal("300"), tuition_covers=False).to_dict(),
    )
    label_, old, new = request.field_changes()[0]
    assert label_ == "Price"
    assert old == "$500, covered by School tuition"
    assert new == "$300"


def test_a_mixed_change_applies_scalars_and_the_price(approved_event):
    event, faculty = approved_event
    request = EventChangeRequest.objects.create(
        event=event, proposed_by=faculty,
        status=EventChangeRequest.Status.PENDING,
        changed_fields=["title", "price"],
        original_title="Reviewed", proposed_title="Reviewed Again",
        original_price=PriceSpec(
            amount=Decimal("500"), tuition_covers=True).to_dict(),
        proposed_price=PriceSpec(
            amount=Decimal("300"), tuition_covers=True).to_dict(),
    )
    request.approve(faculty)
    event.refresh_from_db()
    assert event.title == "Reviewed Again"
    assert from_event(event).amount == Decimal("300")


def test_a_price_change_never_reprices_an_existing_registration(approved_event):
    """Safety property 2."""
    from django.contrib.auth import get_user_model
    from registrations.models import Registration

    event, faculty = approved_event
    member = get_user_model().objects.create_user(
        email="already@example.com", password="pw",
    )
    registration = Registration.objects.create(
        user=member, event=event, price_tier=event.price_tiers.get(),
        quoted_amount=Decimal("500"), status=Registration.Status.PAID,
    )
    request = EventChangeRequest.objects.create(
        event=event, proposed_by=faculty,
        status=EventChangeRequest.Status.PENDING,
        changed_fields=["price"],
        original_price=PriceSpec(
            amount=Decimal("500"), tuition_covers=True).to_dict(),
        proposed_price=PriceSpec(
            amount=Decimal("300"), tuition_covers=True).to_dict(),
    )
    request.approve(faculty)
    registration.refresh_from_db()
    assert registration.quoted_amount == Decimal("500")
```

Check `EventProposal`'s real field name for the minted event before running — if it is not `minted_event`, run `grep -n "minted_event\|related_name=\"from_proposal\"" events/models.py` and use the correct one.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest events/test_price_review.py -v`
Expected: FAIL — `"price" not in REVIEWABLE_FIELDS`, and `TypeError` on the unknown `original_price` kwarg.

- [ ] **Step 3: Add the two model fields**

In `events/models.py`, on `EventChangeRequest`, after `proposed_fee_note` / `original_fee_note`:

```python
    #: Price is a related row, not an Event field, so it travels as a
    #: PriceSpec dict rather than a column per value (task #532).
    proposed_price = models.JSONField(null=True, blank=True)
    original_price = models.JSONField(null=True, blank=True)
```

- [ ] **Step 4: Generate and apply the migration**

```bash
uv run python manage.py makemigrations events -n changerequest_price
uv run python manage.py migrate
```

Expected: one `AddField` per column, no other operations. If anything else appears, a previous task left a model change uncommitted — investigate before continuing.

- [ ] **Step 5: Branch `apply()` and `field_changes()`**

Replace `EventChangeRequest.apply`:

```python
    def apply(self):
        """Copy the proposed values onto the live event."""
        from django.utils import timezone
        from .price_spec import PriceSpec, apply_to_event

        scalar = [f for f in self.changed_fields if f != "price"]
        for f in scalar:
            setattr(self.event, f, getattr(self, f"proposed_{f}"))
        if scalar:
            self.event.save(update_fields=scalar)
        if "price" in self.changed_fields:
            apply_to_event(self.event, PriceSpec.from_dict(self.proposed_price))
        self.applied_at = timezone.now()
```

Replace `EventChangeRequest.field_changes`:

```python
    def field_changes(self):
        """List of ``(label, old, new)`` tuples for the changed fields, for the
        review queue + dialog diff display."""
        from .price_spec import PriceSpec, label
        from .review import FIELD_LABELS
        out = []
        for f in self.changed_fields:
            if f == "price":
                out.append((
                    FIELD_LABELS["price"],
                    label(PriceSpec.from_dict(self.original_price)),
                    label(PriceSpec.from_dict(self.proposed_price)),
                ))
                continue
            out.append((
                FIELD_LABELS.get(f, f),
                getattr(self, f"original_{f}"),
                getattr(self, f"proposed_{f}"),
            ))
        return out
```

- [ ] **Step 6: Teach `review.py` about price**

In `events/review.py`:

```python
REVIEWABLE_FIELDS = ("title", "description", "readings", "fee_note", "price")
```

```python
FIELD_LABELS = {
    "title": "Title",
    "description": "Description",
    "readings": "Readings",
    "fee_note": "Fee note",
    "price": "Price",
}
```

Then **delete** `changed_reviewable_fields` entirely. Confirm it is dead first:

Run: `grep -rn "changed_reviewable_fields" --include=*.py . | grep -v .claude-worktrees`
Expected: only the definition.

It is not merely unused — it reads `getattr(event, f)` at call time, and `event_edit` must snapshot the originals *before* binding because ModelForm mutates the instance in place. So the helper would return wrong answers for the only view that could use it. A dead helper that silently disagrees with the live code is exactly what produced this task's bug (`Program.public_program_year_q`); leaving a second one in place invites the next one.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest events/test_price_review.py -v`
Expected: all 6 PASS.

- [ ] **Step 8: Mount the mixin on the faculty form**

In `events/forms.py`:

```python
class EventEditForm(PriceFieldsMixin, forms.ModelForm):
```

At the end of `EventEditForm.__init__` (add one if the class has none, calling `super().__init__(*args, **kwargs)` first):

```python
        self.init_price_fields(self.instance if self.instance.pk else None)
```

And a `clean`:

```python
    def clean(self):
        data = super().clean()
        return self.clean_price(data)
```

- [ ] **Step 9: Wire the view**

Four edits in `events/views.py::event_edit`. Price is not an `Event` attribute, so every place the view assumes `getattr(event, f)` needs a branch.

**9a — import and snapshot the original price before binding** (the existing comment explains why the snapshot must precede `EventEditForm(request.POST, …)`). Replace the `original = …` line:

```python
    from .price_spec import from_event

    original = {
        f: (getattr(event, f) or "")
        for f in REVIEWABLE_FIELDS if f != "price"
    }
    original_price = from_event(event)
```

**9b — include price when computing `changed`.** Replace the `changed = [...]` line:

```python
    cd = form.cleaned_data
    changed = [
        f for f in REVIEWABLE_FIELDS
        if f != "price" and (cd[f] or "") != original[f]
    ]
    # cd["price"] is None for a read-only multi-tier event, meaning "untouched".
    if cd.get("price") is not None and cd["price"] != original_price:
        changed.append("price")
```

**9c — apply the price on the straight-through path.** Replace that early-return block:

```python
    if not changed or not event.requires_change_review():
        form.save()
        form.save_price(event)
        messages.success(request, "Changes saved.")
        return redirect("events:detail", slug=event.slug)
```

**9d — keep the price inputs out of `nonreviewable`, and feed the two JSON columns.**

This is the trap: `fee_amount`, `fee_type` and friends appear in `form.changed_data` but are not `Event` fields, so the existing `setattr(event, f, cd[f])` + `event.save(update_fields=concrete)` would raise `FieldDoesNotExist`. Replace the `nonreviewable = [...]` comprehension:

```python
    nonreviewable = [
        f for f in form.changed_data
        if f not in REVIEWABLE_FIELDS and f not in EventEditForm.PRICE_FIELDS
    ]
```

And replace `_make_request` entirely:

```python
    def _make_request(status):
        scalar = [f for f in changed if f != "price"]
        extra = {}
        if "price" in changed:
            extra["proposed_price"] = cd["price"].to_dict()
            extra["original_price"] = (
                original_price.to_dict() if original_price else None
            )
        return EventChangeRequest(
            event=event, proposed_by=request.user, status=status,
            changed_fields=changed, description_change_ratio=desc_ratio,
            **{f"proposed_{f}": cd[f] for f in scalar},
            **{f"original_{f}": original[f] for f in scalar},
            **extra,
        )
```

The `review` / `admin` / `minor` branches below need no change — they call `_make_request` and `cr.apply()`, both of which are now price-aware.

- [ ] **Step 10: Include the partial on the faculty form**

In `events/templates/events/event_edit.html`, after the `fee_note` block (around line 90):

```html
      {% include "events/_price_fields.html" %}
```

- [ ] **Step 11: Carry `tuition_covers` across the review re-post**

In `events/templates/events/event_edit_confirm.html`, the loop re-emits every field as a hidden `<textarea>`, which round-trips an unchecked checkbox as the string `"False"`. `CheckboxInput.value_from_datadict` maps `"false"` to False, so this works — but `record_video` is already special-cased there, so follow that precedent rather than relying on it:

```html
      {% if field.name == "record_video" or field.name == "tuition_covers" %}
        {% if field.value %}<input type="hidden" name="{{ field.name }}" value="on">{% endif %}
      {% else %}
```

- [ ] **Step 12: Test the re-post survives**

Append to `events/test_price_review.py`:

```python
def test_a_price_change_survives_the_confirm_dialog_repost(client, approved_event):
    """The dialog re-posts the form as hidden inputs; the price must ride along."""
    from django.urls import reverse

    event, faculty = approved_event
    client.force_login(faculty)
    url = reverse("events:edit", args=[event.slug])
    payload = {
        "title": event.title, "description": event.description,
        "readings": "", "schedule_note": "", "contact": "", "fee_note": "",
        "fee_type": "fixed", "fee_amount": "300", "tuition_covers": "on",
        "decision": "review",
    }
    response = client.post(url, payload)
    assert response.status_code in (200, 302)
    request = EventChangeRequest.objects.filter(event=event).latest("created_at")
    assert "price" in request.changed_fields
    assert PriceSpec.from_dict(request.proposed_price).amount == Decimal("300")
    event.refresh_from_db()
    assert from_event(event).amount == Decimal("500")  # untouched while pending
```

Run: `uv run pytest events/test_price_review.py -v`
Expected: all 7 PASS. If the POST 200s with form errors, print `response.context["form"].errors` and add the missing required fields to `payload` — do not weaken the assertions.

- [ ] **Step 13: Verify in a browser**

Run: `npm run build:css` then `uv run python manage.py runserver`

As faculty on an approved seminar, change the price at `/events/<slug>/edit/`, confirm the dialog lists "Price" with old and new labels, choose "substantial", and check the PC's Changes tab shows the same diff. Approve it and confirm the live price moves.

- [ ] **Step 14: Run the full suite and lint**

Run: `uv run pytest && uv run ruff check .`
Expected: all green.

- [ ] **Step 15: Commit**

```bash
git add events/models.py events/migrations/ events/review.py events/forms.py events/views.py events/templates/events/event_edit.html events/templates/events/event_edit_confirm.html events/test_price_review.py
git commit -m "feat(events): a faculty price change routes through PC review (task #532)"
```

---

## Final verification

- [ ] `uv run pytest` — full suite green.
- [ ] `uv run ruff check .` — clean.
- [ ] `grep -rn "published=True" events/upcoming.py core/views.py events/views.py` — no remaining raw-flag filters on the three fixed querysets.
- [ ] Update `CLAUDE.md`'s status section with a task #532 entry, following the house style of the entries above it.
- [ ] Merge to `main` and push; confirm the Deploy workflow goes **green** — a red CI silently aborts the deploy, so a push is not a deploy.
