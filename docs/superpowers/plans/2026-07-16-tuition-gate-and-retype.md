# Tuition Clearance Gate + Payment Re-categorize Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Block promotion to Analyst/Scholar while tuition is unsettled (every role-change surface), and give the treasurer a first-class audited payment re-categorize action.

**Architecture:** One clearance predicate in `payments/ledger.py` consumed by a shared validator in `accounts/membership.py`; enforcement at the `record_membership_change` chokepoint plus friendly form/view errors at each surface (Meeting advancement, Board membership admin, Django admin, CSV importer). Re-categorize is a new treasurer POST view + per-row disclosure forms. Spec: `docs/superpowers/specs/2026-07-16-tuition-gate-and-retype-design.md`.

**Tech Stack:** Django 5.2, pytest-django, DaisyUI v5 templates.

## Global Constraints

- **Work in the worktree**: paths relative to `/Users/picone/LSP-Web-Coordinator/lsp-website/.claude-worktrees/eager-falcon`. NEVER edit the main repo path.
- `uv run pytest <file> -q` / `uv run ruff check .` green at every commit.
- Gate scope: fires ONLY when target role ∈ {analyst, scholar}, the member's CURRENT role ∈ `Profile.IN_TRAINING_ROLES`, and `tuition_clearance` returns reasons. External→analyst (bootstrap/board records) passes freely. Personas always pass.
- No override flag anywhere — the ledger levers (record payment / adjust / waive / void) are the override; block messages must say so.
- Money is Decimal. Templates: DaisyUI semantic tokens only; member-facing copy uses commas, not em dashes (all UI here is staff-facing — match existing treasurer/formation template tone).
- Existing test idiom: tests that build periods delete the seeded ones first; in-training test users need `profile.role = "candidate"` (+save) or tuition history is frozen.
- Commit per task: `feat(...): … (task #439)`.

---

### Task 1: `ledger.tuition_clearance(user)`

**Files:**
- Modify: `payments/ledger.py`
- Test: `payments/test_tuition_clearance.py`

**Interfaces:**
- Produces: `tuition_clearance(user) -> list[str]` — `[]` = clear. Reasons: one per non-void, non-waived tuition charge whose sweep state ≠ `"paid"` (`"AY 2025–2026 tuition charge has $1,675.00 uncovered."` — for a period-less charge use `"A tuition charge has $X uncovered."`); plus `"N of 4 tuition years covered."` when `tuition_years_covered < TUITION_YEARS_REQUIRED`. Personas → `[]`.
- Consumes: `member_account(user)` (its `lines`/`charge_states`/`tuition_years_covered` keys).

- [ ] **Step 1: Write the failing tests**

```python
# payments/test_tuition_clearance.py
"""tuition_clearance — the promotion gate's one source of truth (task #439)."""

from datetime import date, datetime
from datetime import timezone as tz
from decimal import Decimal

import pytest

from accounts.models import User
from payments import ledger
from payments.models import Charge, DuesPeriod, Payment, TuitionEnrollment, TuitionPeriod

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_periods():
    TuitionPeriod.objects.all().delete()
    DuesPeriod.objects.all().delete()


def _candidate(email, persona=False):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = "candidate"
    u.profile.is_persona = persona
    u.profile.save()
    return u


def _year(start, amount="2000"):
    return TuitionPeriod.objects.create(
        name=f"AY {start}-{start + 1}", slug=f"t-{start}",
        start_date=date(start, 9, 1), end_date=date(start + 1, 8, 31),
        decision_due_date=date(start, 8, 31), tuition_amount=Decimal(amount))


def _enroll(u, tp, status=TuitionEnrollment.Status.COMMITTED):
    return TuitionEnrollment.objects.create(
        user=u, tuition_period=tp, status=status, source="staff")


def _pay(u, amount):
    p = Payment.objects.create(
        user=u, payment_type=Payment.Type.TUITION, amount=Decimal(amount),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE)
    Payment.objects.filter(pk=p.pk).update(
        paid_at=datetime(2025, 10, 1, tzinfo=tz.utc))


def _four_paid_years(u):
    for i in range(4):
        _enroll(u, _year(2021 + i))
    _pay(u, "8000")


def test_clear_when_four_years_covered():
    u = _candidate("cl1@x.test")
    _four_paid_years(u)
    assert ledger.tuition_clearance(u) == []


def test_uncovered_charge_blocks_with_amount():
    u = _candidate("cl2@x.test")
    for i in range(4):
        _enroll(u, _year(2021 + i))
    _pay(u, "6325")   # 3 years + $325 of the 4th
    reasons = ledger.tuition_clearance(u)
    assert any("$1675.00 uncovered" in r for r in reasons)


def test_missing_years_block():
    u = _candidate("cl3@x.test")
    for i in range(3):
        _enroll(u, _year(2021 + i))
    _pay(u, "6000")   # 3 years fully paid, no 4th enrollment
    reasons = ledger.tuition_clearance(u)
    assert reasons == ["3 of 4 tuition years covered."]


def test_waived_charge_counts_as_settled_but_not_covered():
    u = _candidate("cl4@x.test")
    for i in range(4):
        _enroll(u, _year(2021 + i))
    _pay(u, "6000")
    last = Charge.objects.filter(user=u).order_by("-effective_date").first()
    last.status = Charge.Status.WAIVED
    last.staff_adjusted = True
    last.save()
    reasons = ledger.tuition_clearance(u)
    # No "uncovered" reason (waived is settled), but only 3 years COVERED.
    assert not any("uncovered" in r for r in reasons)
    assert "3 of 4 tuition years covered." in reasons


def test_persona_always_clear():
    u = _candidate("cl5@x.test", persona=True)
    _enroll(u, _year(2021))
    assert ledger.tuition_clearance(u) == []
```

**Design note baked into the waived test:** a WAIVED year is *settled* (no money owed) but does NOT count toward the four covered years — the treasurer who waives a required year must also be waiving the requirement, so the gate still reports "3 of 4". If the school wants a waived year to count, that's a policy change made by voiding the charge and recording the year another way; the message tells the Meeting exactly what state things are in.

- [ ] **Step 2: Run to verify failure** — `uv run pytest payments/test_tuition_clearance.py -q` → `AttributeError: … no attribute 'tuition_clearance'`

- [ ] **Step 3: Implement (append to `payments/ledger.py`)**

```python
def tuition_clearance(user) -> list[str]:
    """Reasons a member's tuition standing blocks promotion to Analyst/Scholar.

    Empty list = clear. Necessary-but-insufficient: completing the Passage /
    Traversée remains the Meeting of Analysts' decision — this is only the
    financial criterion (spec 2026-07-16). Personas are exempt. No override
    flag exists: settling the ledger (record payment / adjust / waive / void)
    is the override.
    """
    profile = getattr(user, "profile", None)
    if profile is None or profile.is_persona:
        return []
    acct = member_account(user)
    reasons = []
    # Replay the account's oldest-first sweep over the statement lines and
    # report the uncovered slice of every OPEN tuition charge.
    remaining = acct["paid"]
    for ln in acct["lines"]:
        if ln["kind"] != "charge" or not ln["counts"]:
            continue  # payments, waived charges: no obligation to cover
        c = ln["obj"]
        covered = min(c.amount, remaining)
        remaining -= covered
        if c.category != Charge.Category.TUITION:
            continue
        uncovered = c.amount - covered
        if uncovered > 0:
            where = (f"{c.tuition_period.name} tuition charge"
                     if c.tuition_period_id else "A tuition charge")
            reasons.append(f"{where} has ${uncovered} uncovered.")
    if acct["tuition_years_covered"] < acct["tuition_years_required"]:
        reasons.append(
            f"{acct['tuition_years_covered']} of "
            f"{acct['tuition_years_required']} tuition years covered.")
    return reasons
```
- [ ] **Step 4: Run tests** — `uv run pytest payments/test_tuition_clearance.py payments/test_ledger.py -q` → all pass

- [ ] **Step 5: Commit** — `git add payments/ledger.py payments/test_tuition_clearance.py && git commit -m "feat(payments): tuition_clearance — the promotion gate predicate (task #439)"`

---

### Task 2: Chokepoint guard — `validate_role_transition` + `record_membership_change`

**Files:**
- Modify: `accounts/membership.py`
- Test: `accounts/test_role_gate.py`

**Interfaces:**
- Produces: `accounts.membership.validate_role_transition(user, new_role) -> None` — raises `django.core.exceptions.ValidationError` (whose `.messages` are the clearance reasons plus the fix-path sentence) iff `new_role in {"analyst", "scholar"}`, `user.profile.role in Profile.IN_TRAINING_ROLES`, and `payments.ledger.tuition_clearance(user)` is non-empty. `record_membership_change` calls it first.
- Consumes: Task 1's predicate.

- [ ] **Step 1: Write the failing tests**

```python
# accounts/test_role_gate.py
"""Tuition clearance gate at the record_membership_change chokepoint (task #439)."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from accounts.membership import current_academic_year_start, record_membership_change
from accounts.models import Profile, User
from payments.models import DuesPeriod, TuitionEnrollment, TuitionPeriod

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_periods():
    TuitionPeriod.objects.all().delete()
    DuesPeriod.objects.all().delete()


def _candidate_owing(email):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = "candidate"
    u.profile.save()
    tp = TuitionPeriod.objects.create(
        name="AY 2025-2026", slug="t-2025", start_date=date(2025, 9, 1),
        end_date=date(2026, 8, 31), decision_due_date=date(2025, 8, 31),
        tuition_amount=Decimal("2000"))
    TuitionEnrollment.objects.create(
        user=u, tuition_period=tp, status=TuitionEnrollment.Status.COMMITTED,
        source="staff")
    return u


def _promote(u, role="analyst"):
    return record_membership_change(
        u, role=role, standing=Profile.Standing.ACTIVE,
        effective_ay=current_academic_year_start())


def test_owing_candidate_cannot_become_analyst():
    u = _candidate_owing("rg1@x.test")
    with pytest.raises(ValidationError) as exc:
        _promote(u)
    assert any("uncovered" in m for m in exc.value.messages)
    assert any("treasurer account page" in m for m in exc.value.messages)
    u.profile.refresh_from_db()
    assert u.profile.role == "candidate"          # nothing changed
    assert u.tenures.count() <= 1                 # no tenure written


def test_external_to_analyst_passes_freely():
    u = User.objects.create_user(email="rg2@x.test", password="x")  # external
    _promote(u)
    u.profile.refresh_from_db()
    assert u.profile.role == "analyst"


def test_non_analyst_targets_unaffected():
    u = _candidate_owing("rg3@x.test")
    _promote(u, role="candidate")                 # lateral: no gate
    u.profile.refresh_from_db()
    assert u.profile.role == "candidate"


def test_settled_candidate_promotes():
    u = _candidate_owing("rg4@x.test")
    from payments.models import Charge
    for c in Charge.objects.filter(user=u):       # treasurer voids the charge
        c.status = Charge.Status.VOID
        c.staff_adjusted = True
        c.save()
    # …but 0 of 4 years covered still blocks:
    with pytest.raises(ValidationError):
        _promote(u)
```

(Check the reverse accessor for MembershipTenure — the first test uses `u.tenures`; grep `related_name` on `MembershipTenure.user` and adjust.)

**Design note:** `test_settled_candidate_promotes` pins the strict rule — voiding the debt alone doesn't create four covered years. Real promotions have four paid years; the gate's message tells the Meeting which criterion is missing.

- [ ] **Step 2: Run to verify failure** — `uv run pytest accounts/test_role_gate.py -q` → ImportError on `validate_role_transition` absence is fine at collection if imported; the first test fails because no gate exists.

- [ ] **Step 3: Implement (in `accounts/membership.py`)**

```python
GATED_ROLES = frozenset({"analyst", "scholar"})

FIX_PATH = ("Resolve on the member's treasurer account page (record payment, "
            "adjust, waive, or void), then retry.")


def validate_role_transition(user, new_role) -> None:
    """Refuse promotion out of training while tuition is unsettled.

    Necessary but insufficient — the Passage/Traversée decision stays with
    the Meeting of Analysts. No override flag: the ledger is the override
    (spec 2026-07-16).
    """
    from django.core.exceptions import ValidationError

    from accounts.models import Profile

    if new_role not in GATED_ROLES:
        return
    profile = getattr(user, "profile", None)
    if profile is None or profile.role not in Profile.IN_TRAINING_ROLES:
        return  # not a promotion out of training (bootstrap/external records)
    from payments.ledger import tuition_clearance

    reasons = tuition_clearance(user)
    if reasons:
        raise ValidationError(reasons + [FIX_PATH])
```

In `record_membership_change`, immediately after the docstring:

```python
    validate_role_transition(member, role)
```

- [ ] **Step 4: Run** — `uv run pytest accounts/test_role_gate.py accounts formation -q` → all pass (formation suite exercises `decide_advancement` → chokepoint; its fixtures must still pass because their members either aren't owing or aren't in-training — if any formation test now fails on the gate, give its member four paid years via the Task 1 helpers pattern, matching real promotion preconditions; list every such adaptation in the report).

- [ ] **Step 5: Commit** — `git add accounts/membership.py accounts/test_role_gate.py formation/ && git commit -m "feat(accounts): tuition clearance gate at the membership chokepoint (task #439)"`

---

### Task 3: Meeting of Analysts advancement — pre-check, friendly errors, standing panel, queue badge

**Files:**
- Modify: `formation/advancement.py` (`decide_advancement`), `formation/views.py` (`advancement_decide`, `advancement_detail`, `advancement_queue`)
- Modify: `formation/templates/formation/advancement_detail.html`, `formation/templates/formation/advancement_queue.html`
- Test: `formation/test_advancement_gate.py`

**Interfaces:**
- Produces: `decide_advancement(..., approve=True)` raises `ValidationError` before any write when blocked (the chokepoint would too — this pre-check keeps the Advancement row untouched). `advancement_decide` catches `ValidationError` → `messages.error("Cannot approve — " + "; ".join(e.messages))` → redirect to detail. `advancement_detail` context gains `tuition_reasons` (list) computed via `ledger.tuition_clearance(adv.member)` for PASSAGE-kind advancements targeting gated roles (else `None`). `advancement_queue` rows gain `tuition_blocked` flag.
- Consumes: Tasks 1–2.

- [ ] **Step 1: Write the failing tests**

```python
# formation/test_advancement_gate.py
"""The Meeting sees tuition standing and cannot approve past it (task #439)."""
```

Test list (write real tests following `formation/`'s existing fixture idioms — read `formation/test_formation.py`'s advancement tests first and reuse its helpers for creating an Advancement and a reviewer):
1. `test_decide_blocked_leaves_advancement_open` — owing candidate + open PASSAGE advancement; `decide_advancement(..., approve=True)` raises `ValidationError`; advancement still `is_open`, member still candidate.
2. `test_decide_view_shows_friendly_error` — POST approve via the client as a reviewer → 302 back to detail, `messages` contains "Cannot approve", advancement still open.
3. `test_detail_shows_tuition_standing` — GET detail as reviewer: blocked member → response contains "Tuition standing" and an "uncovered" reason; settled member (four paid years) → contains "Tuition standing" and "clear".
4. `test_queue_badges_blocked_rows` — queue page contains a "tuition" badge for the blocked member's row.
5. `test_decline_never_blocked` — declining an owing member's advancement works unchanged.

- [ ] **Step 2: Run to verify failure** — `uv run pytest formation/test_advancement_gate.py -q`

- [ ] **Step 3: Implement**

`formation/advancement.py` — in `decide_advancement`, inside the `if approve:` branch after computing `target_role`:

```python
        from accounts.membership import validate_role_transition

        validate_role_transition(advancement.member, target_role)
```

`formation/views.py`:

- `advancement_decide`: wrap the `decision == "approve"` call:

```python
        from django.core.exceptions import ValidationError
        try:
            decide_advancement(adv, approve=True, by=request.user,
                               effective_ay=effective_ay, note=note)
        except ValidationError as exc:
            messages.error(
                request, "Cannot approve — " + " ".join(exc.messages))
            return redirect("formation:advancement_detail", pk=pk)
```

- `advancement_detail`: add to context (import ledger lazily):

```python
    tuition_reasons = None
    if adv.advance_role in ("analyst", "scholar") and adv.is_open:
        from payments.ledger import tuition_clearance
        tuition_reasons = tuition_clearance(adv.member)
```

pass `"tuition_reasons": tuition_reasons` (None = don't show panel; `[]` = show "clear").

- `advancement_queue`: annotate each open advancement dict/object with `tuition_blocked = bool(tuition_clearance(a.member))` for gated targets (small queue; per-row call is fine).

Templates — `advancement_detail.html`, after the recommendation section (match the file's card classes):

```html
{% if tuition_reasons is not None %}
<section class="space-y-2">
  <h3 class="font-serif text-lg text-base-content">Tuition standing</h3>
  {% if tuition_reasons %}
  <div class="alert alert-warning text-sm">
    <div>
      <p class="font-medium">Tuition must be settled before this promotion can be approved:</p>
      <ul class="list-disc ml-5">
        {% for r in tuition_reasons %}<li>{{ r }}</li>{% endfor %}
      </ul>
    </div>
  </div>
  {% else %}
  <p class="text-sm"><span class="badge badge-success badge-sm">clear</span>
    Tuition requirement settled — no financial block on this promotion.</p>
  {% endif %}
</section>
{% endif %}
```

`advancement_queue.html`: on each row, `{% if row.tuition_blocked %}<span class="badge badge-warning badge-xs" title="Tuition must be settled before approval">tuition</span>{% endif %}` (adapt to the template's actual row variable).

- [ ] **Step 4: Run** — `uv run pytest formation -q` → all pass

- [ ] **Step 5: Commit** — `git add formation/ && git commit -m "feat(formation): tuition standing on advancement — panel, badge, friendly block (task #439)"`

---

### Task 4: Board membership admin + Django admin guards

**Files:**
- Modify: `core/staff.py` (`board_membership_admin`), `accounts/forms.py` (`MembershipChangeForm`), `accounts/admin.py`
- Test: `accounts/test_role_gate.py` (append) + `core`'s existing staff-test idiom

**Interfaces:**
- Produces: `MembershipChangeForm` accepts `member=` kwarg; its `clean()` calls `validate_role_transition(member, cleaned["role"])` and re-raises as a form error. `board_membership_admin` passes `member=`, and additionally wraps its `record_membership_change` call in `try/except ValidationError → messages.error` (belt and suspenders — read `core/staff.py:320-350` first and match its render/redirect flow). A shared `ProfileAdminForm(forms.ModelForm)` in `accounts/admin.py` with `clean_role` calling the validator when `self.instance.pk` exists and role changed; set `form = ProfileAdminForm` on `ProfileAdmin` and `ProfileInline`.
- Consumes: Task 2's validator.

- [ ] **Step 1: Failing tests** (append to `accounts/test_role_gate.py`):

1. `test_membership_form_blocks_owing_promotion` — `MembershipChangeForm(data={role: "analyst", standing: "active", effective_ay: 2026}, member=owing_candidate)` → `not form.is_valid()`, "uncovered" in `form.errors["__all__"][0]` (or role field — match implementation).
2. `test_membership_form_allows_settled` — four-paid-years candidate → valid.
3. `test_profile_admin_form_blocks_role_edit` — build `ProfileAdminForm(instance=owing.profile, data={... role: "analyst" ...})` → invalid with the reason. (Model forms need all required fields — read the Profile model's blank/required fields and pass `initial`-derived data; keep it minimal by using `ProfileAdminForm(data=model_to_dict(profile) | {"role": "analyst"}, instance=profile)`.)
4. `test_profile_admin_form_allows_non_gated_edits` — same form editing bio only → valid.

- [ ] **Step 2: RED** — run the file.

- [ ] **Step 3: Implement.** `MembershipChangeForm.__init__` stores `self.member = kwargs.pop("member", None)`; `clean()`:

```python
    def clean(self):
        cleaned = super().clean()
        role = cleaned.get("role")
        if self.member is not None and role:
            from django.core.exceptions import ValidationError

            from .membership import validate_role_transition
            try:
                validate_role_transition(self.member, role)
            except ValidationError as exc:
                raise forms.ValidationError(exc.messages)
        return cleaned
```

`core/staff.py board_membership_admin`: pass `member=member` at both form constructions (POST and GET — read the view for the member variable name), and wrap the `record_membership_change` call in try/except ValidationError → `messages.error(request, " ".join(exc.messages))` without saving.

`accounts/admin.py`:

```python
from django import forms


class ProfileAdminForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = "__all__"

    def clean_role(self):
        role = self.cleaned_data["role"]
        if self.instance.pk and role != self.instance.role:
            from django.core.exceptions import ValidationError

            from .membership import validate_role_transition
            try:
                validate_role_transition(self.instance.user, role)
            except ValidationError as exc:
                raise forms.ValidationError(" ".join(exc.messages))
        return role
```

Set `form = ProfileAdminForm` on `ProfileAdmin`; on `ProfileInline` the inline's `fields` subset applies — Django handles the fields intersection (`form = ProfileAdminForm` works with `fields` set; verify with the inline test or use `formfield_callback`-free plain assignment and run the admin smoke tests).

- [ ] **Step 4: Run** — `uv run pytest accounts core -q` → all pass

- [ ] **Step 5: Commit** — `git add accounts/ core/ && git commit -m "feat(accounts): tuition gate on Board membership form and Django admin role edits (task #439)"`

---

### Task 5: CSV importer skip + report

**Files:**
- Modify: `accounts/management/commands/import_users.py`
- Test: `accounts/test_role_gate.py` (append) or the importer's existing test file (grep `import_users` tests and follow their idiom)

**Interfaces:**
- Produces: in the `--update` path, before `Profile.objects.filter(user=existing).update(**profile_fields)`: if `profile_fields.get("role") in {"analyst", "scholar"}` and it differs from the current role, call `validate_role_transition(existing, new_role)`; on `ValidationError`, `profile_fields.pop("role")`, warn (`self.stderr.write(WARNING(f"  warning: {email}: role elevation to {role} skipped — tuition not settled: …"))`), still apply the remaining fields. New-user path untouched (external→analyst passes the validator anyway — do NOT add a call there).
- Consumes: Task 2.

- [ ] Steps: failing test (update-path CSV with an owing candidate → role unchanged, other fields updated, warning in stderr; and a clear candidate → role updated), RED, implement, `uv run pytest accounts -q`, commit `feat(accounts): import_users skips gated role elevations (task #439)`.

---

### Task 6: `treasurer_payment_retype` — view, URL, UI on both surfaces

**Files:**
- Modify: `payments/views.py`, `config/urls.py`
- Modify: `payments/templates/payments/treasurer/payments.html`, `payments/templates/payments/treasurer/member_detail.html`
- Test: `payments/test_payment_retype.py`

**Interfaces:**
- Produces: POST `treasurer_payment_retype(payment_id)` at `treasurer/payments/<id>/retype/` (name `treasurer_payment_retype`), staff-gated, `_safe_next`-honoring (fallback `treasurer_payments`). Fields: `payment_type` (must differ from current, else `messages.error` no-op), `dues_period` / `tuition_period` (period id, used when the NEW type is dues/tuition; default = period containing `payment.transaction_date`, else current). Behavior, in one save: append audit note `[date] Re-categorized {old} → {new} by treasurer {email}.` plus ` (was {old FK detail}; unlinked installment #N)` where applicable; set matching period FK; clear non-matching category FKs (`dues_period` when new type ≠ dues; `tuition_period` AND `tuition_installment` when new type ≠ tuition); `source = Source.VERIFIED`. Donation↔non-donation allowed.
- Template context: `treasurer_payments` and `treasurer_member_detail` both gain `dues_periods` + `tuition_periods` lists (newest first) for the selectors.
- Consumes: existing `_is_staff`, `_safe_next`, `Payment` FKs.

- [ ] **Step 1: Failing tests** — `payments/test_payment_retype.py` with the treasurer-client fixture idiom from `payments/test_member_account_actions.py`:

1. `test_retype_tuition_to_registration_clears_fks_and_notes` — tuition payment with `tuition_period` + `tuition_installment` set → retype to registration: FKs cleared, note names old type and unlinked installment, `source == "verified"`.
2. `test_retype_to_dues_binds_period` — donation → dues with explicit `dues_period` id: FK set; ledger pot effect asserted (`member_account(u)["paid"]` grows by the amount — donation left the exclusion).
3. `test_retype_defaults_period_from_payment_date` — no period posted: dues_period containing `paid_at` chosen.
4. `test_noop_retype_refused` — same type → no note appended, message error (assert note unchanged).
5. `test_next_honored` — POST with `next=/treasurer/members/<id>/` → 302 there.
6. `test_requires_staff`.

- [ ] **Step 2: RED.**

- [ ] **Step 3: Implement** the view (mirror `treasurer_charge_update`'s shape):

```python
@login_required
@user_passes_test(_is_staff)
@require_POST
def treasurer_payment_retype(request, payment_id: int):
    """Re-categorize a payment (treasurer override — donation flips allowed).

    The member-side path (my_payments_update) deliberately blocks
    donation↔non-donation; this is the audited staff counterpart."""
    from accounts.models import Source

    payment = get_object_or_404(Payment, pk=payment_id)
    new_type = request.POST.get("payment_type")
    if new_type not in Payment.Type.values:
        messages.error(request, "Choose a valid category.")
        return _safe_next(request, "treasurer_payments")
    if new_type == payment.payment_type:
        messages.error(request, "That payment already has that category.")
        return _safe_next(request, "treasurer_payments")

    old_type = payment.payment_type
    details = []
    if payment.dues_period_id and new_type != Payment.Type.DUES:
        details.append(f"was {payment.dues_period}")
        payment.dues_period = None
    if new_type != Payment.Type.TUITION:
        if payment.tuition_period_id:
            details.append(f"was {payment.tuition_period}")
            payment.tuition_period = None
        if payment.tuition_installment_id:
            details.append(
                f"unlinked installment #{payment.tuition_installment_id}")
            payment.tuition_installment = None

    when = (payment.paid_at or payment.created_at).date()
    if new_type == Payment.Type.DUES:
        payment.dues_period = (
            DuesPeriod.objects.filter(pk=request.POST.get("dues_period") or 0).first()
            or DuesPeriod.objects.filter(
                start_date__lte=when, end_date__gte=when).first()
            or DuesPeriod.current()
        )
    elif new_type == Payment.Type.TUITION:
        payment.tuition_period = (
            TuitionPeriod.objects.filter(pk=request.POST.get("tuition_period") or 0).first()
            or TuitionPeriod.objects.filter(
                start_date__lte=when, end_date__gte=when).first()
            or TuitionPeriod.current()
        )

    payment.payment_type = new_type
    payment.source = Source.VERIFIED
    labels = dict(Payment.Type.choices)
    audit = (f"[{timezone.now().date()}] Re-categorized "
             f"{labels[old_type]} → {labels[new_type]} by treasurer "
             f"{request.user.email}."
             + (f" ({'; '.join(details)})" if details else ""))
    payment.notes = (payment.notes + "\n" + audit) if payment.notes else audit
    payment.save()
    messages.success(request, f"Re-categorized as {labels[new_type]}.")
    return _safe_next(request, "treasurer_payments")
```

URL: `path("treasurer/payments/<int:payment_id>/retype/", _payment_views.treasurer_payment_retype, name="treasurer_payment_retype"),`

Templates: add to the actions cell of `payments.html` rows and the payment rows of `member_detail.html`'s statement a `<details class="dropdown">`-style disclosure titled "Re-categorize" containing: category select (all four types, current pre-selected+disabled label), the two period selects (labelled "Dues year"/"Tuition year", shown always — small note "used only when the matching category is chosen"), hidden `next` = `request.get_full_path`/`request.path`, csrf, submit `btn btn-xs`. Add `dues_periods`/`tuition_periods` to both views' contexts.

- [ ] **Step 4: Run** — `uv run pytest payments/test_payment_retype.py payments -q` → all pass

- [ ] **Step 5: Commit** — `git add payments/ config/urls.py && git commit -m "feat(treasurer): audited payment re-categorize on Payments tab + member statement (task #439)"`

---

### Task 7: Guide, docs, final verification

**Files:**
- Modify: `core/docs/treasurer-guide.md`, `CLAUDE.md`
- Test: full suite

- [ ] **Step 1**: Guide additions (current guide voice; wrapped-list-line gotcha applies): (a) under the tuition/account-model section: promotions to Analyst/Scholar are blocked while tuition is unsettled — the Meeting's advancement page shows the standing; the fix is the member's account page levers; no override switch exists, settling the ledger IS the override. (b) under the member statement / Payments tab actions: the Re-categorize action — what it does, that it moves money in/out of the account pot when donations are involved, that re-typing a transitioned member's tuition payment requires a manual follow-up adjust/void on their frozen charges. (c) Help-tab smoke assertion: extend the existing help test to also assert "Re-categorize" appears.
- [ ] **Step 2**: CLAUDE.md status bullet (one, concise): tuition clearance gate on all role surfaces + treasurer payment re-categorize.
- [ ] **Step 3**: `uv run pytest -q` and `uv run ruff check .` — fully green.
- [ ] **Step 4**: Commit — `docs(treasurer): guide + status for tuition gate and re-categorize (task #439)`.

---

## Deploy & data runbook (after merge — with Rico)

1. Push main → Deploy green (pushed-is-not-deployed).
2. No data migration and no backfill needed — the gate is read-time; re-categorize is on-demand.
3. Treasurer can now do the mis-typed-payment cleanup (Garcia/Tod/Sheila) with the Re-categorize action; for transitioned members, follow up with adjust/void on frozen charges as the guide describes.

## Out of scope (from the spec)

Member-initiated donation-crossing re-categorization (future request→review flow); auto re-sync of frozen charges after re-type; any Passage/Traversée flow change.
