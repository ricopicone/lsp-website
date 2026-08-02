# Provisional seminar coverage for a requested payment plan — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A member whose tuition payment-plan application is pending with the Board gets the same event coverage a tuition commitment gets, and a tuition-eligible special event is waived for both.

**Architecture:** Two behavioral edits, both subtractive. `TuitionEnrollment.covers_seminars` gains `PLAN_REQUESTED` — it is the single source that `Profile.is_tuition_current()` reads, and both consumers (`events.pricing.resolve_price`, `registrations.views._find_covered_tier`) read that, so coverage propagates with no other call site touched. Then the narrow special-event gate (`TUITION_BLOCKING_EVENT_TYPES` plus its branch in `_tuition_block_reason`) is deleted outright, leaving one gate: a decision must be on file. Everything else is copy and docs.

**Tech Stack:** Django 5.2, pytest-django, Django templates (DaisyUI/Tailwind semantic tokens), rendered in-repo markdown docs.

**Spec:** `docs/superpowers/specs/2026-07-29-plan-requested-seminar-coverage-design.md`

## Global Constraints

- **No migration, no backfill, no data change.** `payments.charges._owed_periods` exempts only SKIPPING, so a plan request already mints its tuition charge. Obligations and balances must not move. If you find yourself writing a migration, stop — the plan is wrong.
- **No feature flag and no `FormationSettings` field.** Reversing this policy is a `git revert`.
- **Member-facing site copy uses commas, not em dashes** (convention of 2026-07-06). In-repo markdown docs and code comments use unspaced em dashes (`word—word`).
- **Templates use DaisyUI semantic tokens** (`text-base-content`, `bg-base-200`, …), never hardcoded colors. Every copy change in this plan reuses the classes already on the element it edits, so no new Tailwind classes are introduced.
- **Rendered-markdown gotcha:** in `core/docs/*.md`, a `+`, `-`, or `*` that begins a *wrapped* line inside a list item silently becomes a nested bullet. Keep such characters off the start of continuation lines.
- Run tests with `uv run pytest`, lint with `uv run ruff check .`. Both must be green before the final commit.
- The broad gate stays. Never remove the no-enrollment-row branch of `_tuition_block_reason`.

---

### Task 1: `PLAN_REQUESTED` covers events

**Files:**
- Modify: `payments/models.py:483-494` (`TuitionEnrollment.covers_seminars`)
- Test: `payments/test_tuition.py` (add after `test_payment_plan_status_is_tuition_current`, line 84-91)
- Test: `registrations/test_event_ay_gate.py:83-103` (rewrite `test_plan_requested_not_blocked_but_not_covered`)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `TuitionEnrollment.covers_seminars` returns True for `PLAN_REQUESTED`. Task 2 relies on this (its rewritten test asserts a `PLAN_REQUESTED` member is quoted $0 on a covered special-event tier). Task 3 relies on the status name only.

- [ ] **Step 1: Write the failing profile-level test**

Add to `payments/test_tuition.py` immediately after `test_payment_plan_status_is_tuition_current` (which ends at line 91). It uses the file's existing `current_period` fixture and `_mk_candidate()` helper — do not invent new ones.

```python
@pytest.mark.django_db
def test_plan_requested_status_is_tuition_current(current_period):
    """A plan application pending with the Board covers events, same as a
    commitment (task #484). The year's tuition charge is minted either way."""
    u = _mk_candidate()
    TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.PLAN_REQUESTED,
    )
    assert u.profile.is_tuition_current() is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest payments/test_tuition.py::test_plan_requested_status_is_tuition_current -v`
Expected: FAIL — `assert False is True`.

- [ ] **Step 3: Rewrite the gate test that asserts the old behavior**

In `registrations/test_event_ay_gate.py`, replace the whole of `test_plan_requested_not_blocked_but_not_covered` (lines 83-103) with the version below. Note the name inverts, and the covered tier must be created for the assertion to have anything to resolve.

```python
@pytest.mark.django_db
def test_plan_requested_is_covered(periods, student):
    """A PLAN_REQUESTED enrollment (awaiting the Board's decision on a payment
    plan) has a decision on file, so it clears the broad gate — and since task
    #484 it also covers events, exactly as COMMITTED does. The Board's approval
    sets the installment schedule; it no longer gates registration."""
    from events.models import Audience, PriceTier

    p25, p26 = periods
    TuitionEnrollment.objects.create(
        user=student, tuition_period=p26,
        status=TuitionEnrollment.Status.PLAN_REQUESTED,
    )
    event = Event.objects.create(
        title="Plain Seminar", slug="plain-seminar",
        start_date=date(2026, 9, 15), end_date=date(2027, 6, 1),
    )
    assert event.event_type == Event.Type.SEMINAR
    PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("200"),
        covered_by_tuition=True,
    )

    assert _tuition_block_reason(student, event) is None
    assert _find_covered_tier(student, event) is not None
```

- [ ] **Step 4: Run it to verify it fails**

Run: `uv run pytest registrations/test_event_ay_gate.py::test_plan_requested_is_covered -v`
Expected: FAIL on the last assertion — `_find_covered_tier` returns None.

- [ ] **Step 5: Make both pass**

In `payments/models.py`, replace the `covers_seminars` property (lines 483-494) with:

```python
    @property
    def covers_seminars(self) -> bool:
        """True when this enrollment grants 'covered by tuition' pricing.

        Any non-skipping decision covers, PLAN_REQUESTED included: a plan
        application pending with the Board is a decision to pay, and the
        year's tuition charge is minted for it either way
        (``payments.charges._owed_periods`` exempts only SKIPPING). Waiting on
        the Board's turnaround used to mean paying full seminar fees in the
        meantime — task #484.

        SKIPPING does not cover — the student opted out of tuition this
        year and pays the regular per-event fee.
        """
        return self.status in {
            self.Status.COMMITTED,
            self.Status.PAYMENT_PLAN,
            self.Status.PAID_IN_FULL,
            self.Status.PLAN_REQUESTED,
        }
```

- [ ] **Step 6: Run both tests plus the two suites they live in**

Run: `uv run pytest payments/test_tuition.py registrations/test_event_ay_gate.py -q`
Expected: PASS, no failures. If anything else in these files fails, it is asserting the old no-coverage behavior — read it, and fix the assertion only if it is genuinely about `PLAN_REQUESTED`; anything about COMMITTED or SKIPPING should still be green untouched.

- [ ] **Step 7: Commit**

```bash
git add payments/models.py payments/test_tuition.py registrations/test_event_ay_gate.py
git commit -m "feat(payments): a requested payment plan covers events (#484)"
```

---

### Task 2: Delete the narrow special-event gate

**Files:**
- Modify: `registrations/views.py:94-155` (`TUITION_BLOCKING_EVENT_TYPES`, `_tuition_block_reason`)
- Test: `registrations/test_views.py:658-687` (rewrite `test_special_event_blocks_committed_student_when_event_is_tuition_covered`), plus one new test after it

**Interfaces:**
- Consumes: Task 1's `covers_seminars` change — a `PLAN_REQUESTED` member must resolve a covered tier for the new test to pass.
- Produces: `_tuition_block_reason(user, event) -> str | None` keeps its signature and returns non-None only for the no-decision-on-file case. `TUITION_BLOCKING_EVENT_TYPES` no longer exists; nothing may import it.

- [ ] **Step 1: Rewrite the test that asserts the gate blocks**

In `registrations/test_views.py`, replace the whole of `test_special_event_blocks_committed_student_when_event_is_tuition_covered` (lines 658-687) with the two tests below. They reuse the module's existing `client`, `special_event`, `special_event_tier`, and `tuition_period_2026` fixtures. `"included in your tuition"` is the covered short-circuit page's copy (`registrations/templates/registrations/register_covered.html:18`), so it is the honest signal that coverage was applied rather than merely not blocked.

```python
@pytest.mark.django_db
def test_special_event_covers_committed_student_when_event_is_tuition_covered(
    client, special_event, special_event_tier, tuition_period_2026,
):
    """Task #484 removed the narrow gate: a special event carrying a covered
    tier for the student's audience is waived for COMMITTED, on the assumption
    tuition will be paid. It used to 403 them."""
    from accounts.models import Profile
    from events.models import Audience, PriceTier
    from payments.models import TuitionEnrollment

    u = User.objects.create_user(email="cand3@example.com", password="x")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.save()
    PriceTier.objects.create(
        event=special_event, audience=Audience.CANDIDATE,
        base_amount=Decimal("50.00"), covered_by_tuition=True,
    )
    TuitionEnrollment.objects.create(
        user=u, tuition_period=tuition_period_2026,
        status=TuitionEnrollment.Status.COMMITTED,
    )
    client.force_login(u)
    resp = client.get(
        reverse("registrations:register", args=[special_event.slug])
    )
    assert resp.status_code == 200
    assert b"included in your tuition" in resp.content


@pytest.mark.django_db
def test_special_event_covers_plan_requested_student(
    client, special_event, special_event_tier, tuition_period_2026,
):
    """A pending plan application is in parity with COMMITTED (task #484)."""
    from accounts.models import Profile
    from events.models import Audience, PriceTier
    from payments.models import TuitionEnrollment

    u = User.objects.create_user(email="cand8@example.com", password="x")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.save()
    PriceTier.objects.create(
        event=special_event, audience=Audience.CANDIDATE,
        base_amount=Decimal("50.00"), covered_by_tuition=True,
    )
    TuitionEnrollment.objects.create(
        user=u, tuition_period=tuition_period_2026,
        status=TuitionEnrollment.Status.PLAN_REQUESTED,
    )
    client.force_login(u)
    resp = client.get(
        reverse("registrations:register", args=[special_event.slug])
    )
    assert resp.status_code == 200
    assert b"included in your tuition" in resp.content
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest registrations/test_views.py -k "special_event_covers" -v`
Expected: the COMMITTED one FAILs with `assert 403 == 200`. The `PLAN_REQUESTED` one already passes (Task 1 gave it coverage, and it was never gated) — that is fine, it is a regression guard.

- [ ] **Step 3: Delete the gate**

In `registrations/views.py`, delete the `TUITION_BLOCKING_EVENT_TYPES` constant and its comment block (lines 94-98) entirely, and replace `_tuition_block_reason` (lines 101-155) with:

```python
def _tuition_block_reason(user, event) -> str | None:
    """Return a human-readable reason if the user is blocked from registering
    for this event due to unsettled-tuition status, or None to allow.

    One gate (M7.5, narrowed to this by task #484): in-training students
    (pre-candidate / candidate / pre-candidate-scholar / candidate-scholar)
    who have not recorded a tuition decision for the event's academic year
    are blocked from registering for *any* event. Some decision — even
    SKIPPING — must be on file before they can register for anything.

    There is no longer a second gate. A special event carrying a
    ``covered_by_tuition`` tier is waived for every non-skipping decision,
    COMMITTED and PLAN_REQUESTED included, on the assumption tuition will be
    paid (Rico, 2026-07-29). Coverage itself is decided per event by whoever
    configures its price tiers, so an event with no covered tier for the
    student's audience charges them the regular fee regardless of status.
    """
    profile = getattr(user, "profile", None)
    if not (profile and profile.owes_tuition):
        return None
    from payments.ledger import tuition_decision_exempt
    if tuition_decision_exempt(user):
        return None  # four non-skipping years on record — no annual decision
    from payments.ledger import period_for_event
    from payments.models import TuitionEnrollment
    period = period_for_event(event)
    if period is None:
        return None
    enr = TuitionEnrollment.objects.filter(
        user=user, tuition_period=period,
    ).first()
    if enr is None:
        return (
            "Before registering for any event, please record your tuition "
            f"decision for {period.name}. You'll be able to commit to pay, "
            "set up a payment plan, or note that you're skipping tuition "
            "this year — all options unlock registration."
        )
    return None
```

- [ ] **Step 4: Confirm nothing else referenced the deleted constant**

Run: `grep -rn "TUITION_BLOCKING_EVENT_TYPES" --include=*.py --include=*.html --include=*.md .`
Expected: no hits outside `docs/superpowers/` (the spec and this plan). A hit in `core/docs/treasurer-guide.md` prose is Task 5's job, not a code reference.

- [ ] **Step 5: Run the registration suite**

Run: `uv run pytest registrations/ -q`
Expected: PASS. These four must be green without edits — they are the boundary of the change: `test_undecided_in_training_student_is_blocked_from_special_event`, `test_special_event_allows_skipping_student`, `test_special_event_allows_committed_student_when_event_is_not_tuition_covered`, `test_special_event_without_covered_tier_charges_tuition_student`.

- [ ] **Step 6: Commit**

```bash
git add registrations/views.py registrations/test_views.py
git commit -m "feat(registrations): waive tuition-eligible special events for any non-skipping decision (#484)"
```

---

### Task 3: A covered year reads "Paid" for a pending plan request

**Files:**
- Modify: `payments/ledger.py:196-205` (the Decision-column label inside `member_account`)
- Test: `payments/test_ledger.py` (add after `test_covered_year_decision_label_reads_paid`, line 565-578)

**Interfaces:**
- Consumes: the `PLAN_REQUESTED` status name only.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

Add to `payments/test_ledger.py` immediately after `test_covered_year_decision_label_reads_paid` (ends line 578). It reuses that file's existing `member` fixture and `_tuition_period` / `_pay` / `WHEN` helpers.

```python
def test_covered_year_reads_paid_for_a_pending_plan_request(member):
    """A PLAN_REQUESTED year the sweep fully covers reads 'Paid' rather than a
    stale 'Payment plan requested' (task #484)."""
    t25 = _tuition_period(2025, "2000")
    TuitionEnrollment.objects.create(
        user=member, tuition_period=t25,
        status=TuitionEnrollment.Status.PLAN_REQUESTED, source="staff")
    _pay(member, Payment.Type.TUITION, "2000", WHEN)
    row = ledger.member_account(member)["tuition_rows"][0]
    assert row["state"] == "paid"
    assert row["decision_label"] == "Paid"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest payments/test_ledger.py::test_covered_year_reads_paid_for_a_pending_plan_request -v`
Expected: FAIL — `assert 'Payment plan requested' == 'Paid'`.

- [ ] **Step 3: Add the status to the label set**

In `payments/ledger.py`, the block at lines 196-205 currently reads:

```python
        if state == "paid" and e.status in (
            TuitionEnrollment.Status.COMMITTED,
            TuitionEnrollment.Status.PAYMENT_PLAN,
        ):
```

Change that tuple to include the pending request:

```python
        if state == "paid" and e.status in (
            TuitionEnrollment.Status.COMMITTED,
            TuitionEnrollment.Status.PAYMENT_PLAN,
            TuitionEnrollment.Status.PLAN_REQUESTED,
        ):
```

- [ ] **Step 4: Run the ledger suite**

Run: `uv run pytest payments/test_ledger.py -q`
Expected: PASS, including `test_uncovered_year_decision_label_is_the_decision` (an *uncovered* year still shows the decision itself).

- [ ] **Step 5: Commit**

```bash
git add payments/ledger.py payments/test_ledger.py
git commit -m "fix(payments): a covered year reads Paid for a pending plan request (#484)"
```

---

### Task 4: Copy — member, Board, and the decline notification

**Files:**
- Modify: `formation/templates/formation/_tab_account.html:176-179` and `:230-233` (current-period and upcoming-period pending notes)
- Modify: `payments/templates/payments/tuition_plan_queue.html:13`
- Modify: `payments/notifications.py:217-234` (`notify_plan_application_decided`)
- Test: `formation/test_account_tab.py` (add at the end, after `test_split_action_hidden_when_already_split`)
- Test: `payments/test_plan_review_queue.py:180-196` (extend `test_decline_deletes_enrollment_and_notifies`)

**Interfaces:**
- Consumes: nothing. Copy only.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing account-tab test**

Add at the end of `formation/test_account_tab.py`. It uses that file's `_user()` helper and the module-level `pytestmark = pytest.mark.django_db`.

```python
# ---- 6. Pending payment-plan note (task #484) --------------------------------

def test_pending_plan_note_says_coverage_already_applies(client):
    """A member waiting on the Board is told their tuition already covers
    seminar fees — the group label is the whole disclosure (task #484)."""
    member = _user("planpending@x.test")
    period = TuitionPeriod.current()
    if period is None:
        period = TuitionPeriod.objects.create(
            name="Test AY", slug="test-ay-planpending",
            start_date=timezone.now().date(),
            decision_due_date=timezone.now().date(),
            end_date=timezone.now().date(), tuition_amount=Decimal("800.00"),
        )
    TuitionEnrollment.objects.create(
        user=member, tuition_period=period,
        status=TuitionEnrollment.Status.PLAN_REQUESTED,
    )
    client.force_login(member)
    body = client.get(reverse("formation:formation") + "?tab=account").content.decode()
    assert "Your payment plan application is with the Board." in body
    assert "covers seminar fees" in body
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest formation/test_account_tab.py::test_pending_plan_note_says_coverage_already_applies -v`
Expected: FAIL on `assert "covers seminar fees" in body`.

- [ ] **Step 3: Update both pending notes in the account tab**

In `formation/templates/formation/_tab_account.html`, the current-period note at lines 177-179 reads:

```html
        <div class="rounded-lg border border-base-300 bg-base-200/40 px-5 py-4 text-sm">
          Your payment plan application is with the Board.
        </div>
```

Replace the text line (keep the wrapper and its classes exactly as they are):

```html
        <div class="rounded-lg border border-base-300 bg-base-200/40 px-5 py-4 text-sm">
          Your payment plan application is with the Board. In the meantime your tuition covers seminar fees, just as it does for anyone paying tuition this year.
        </div>
```

Make the identical text change to the upcoming-period note at lines 231-233 (same sentence; that block's wrapper is indented two spaces further — preserve its existing indentation and classes).

Commas, not em dashes: this is member-facing copy.

- [ ] **Step 4: Run the account-tab suite**

Run: `uv run pytest formation/test_account_tab.py -q`
Expected: PASS.

- [ ] **Step 5: Write the failing decline-notification test**

In `payments/test_plan_review_queue.py`, extend `test_decline_deletes_enrollment_and_notifies` (lines 180-196) by adding two assertions after the existing `assert "unable to approve" in note.title`:

```python
    # Provisional coverage was live while the request was pending, so the
    # decline has to mention anything registered under it (task #484).
    assert "tuition coverage" in note.body
    assert "settling" in note.body
```

- [ ] **Step 6: Run it to verify it fails**

Run: `uv run pytest payments/test_plan_review_queue.py::test_decline_deletes_enrollment_and_notifies -v`
Expected: FAIL — `note.body` is `''`.

- [ ] **Step 7: Add the line to the decline branch**

In `payments/notifications.py`, replace `notify_plan_application_decided` (lines 217-234) with:

```python
def notify_plan_application_decided(application) -> None:
    """Tell the applicant the Board's decision on their payment-plan
    application (task #450 phase B)."""
    from .models import TuitionPlanApplication

    period = application.tuition_period
    body = ""
    if application.status == TuitionPlanApplication.Status.APPROVED:
        title = f"The Board approved your payment plan application for {period.name}."
    else:
        title = (
            "The Board was unable to approve your payment plan application "
            f"for {period.name}. Please choose to pay in full or skip this "
            "year on your Account tab."
        )
        # A pending request carried event coverage (task #484), so a decline
        # can leave a $0 registration behind. Nothing unwinds automatically —
        # staff settle it, and the member should not be surprised.
        body = (
            "If you registered for an event with tuition coverage while your "
            "application was pending, we'll be in touch about settling it."
        )
    notify(
        application.user, Category.TUITION_PLAN_REVIEW,
        title=title, body=body, url=_account_tab_url(), target=application,
    )
```

- [ ] **Step 8: Run the plan-review suite**

Run: `uv run pytest payments/test_plan_review_queue.py -q`
Expected: PASS, including `test_approve_flips_enrollment_and_notifies` (the approve branch keeps an empty body).

- [ ] **Step 9: Update the Board's queue intro**

In `payments/templates/payments/tuition_plan_queue.html`, line 13 currently reads:

```html
    <p class="text-base-content/70">Members' requests for a Board-approved payment plan. Approving moves their enrollment to "on payment plan", declining returns it to no decision so they can choose to pay in full or skip the year.</p>
```

Append one sentence, so the Board does not read its own queue as the thing holding members up:

```html
    <p class="text-base-content/70">Members' requests for a Board-approved payment plan. Approving moves their enrollment to "on payment plan", declining returns it to no decision so they can choose to pay in full or skip the year. A pending request already carries tuition coverage for events, so approving sets the installment schedule rather than unlocking registration.</p>
```

- [ ] **Step 10: Commit**

```bash
git add formation/templates/formation/_tab_account.html formation/test_account_tab.py payments/notifications.py payments/test_plan_review_queue.py payments/templates/payments/tuition_plan_queue.html
git commit -m "feat(payments): say that a pending plan request already carries coverage (#484)"
```

---

### Task 5: Docs — the treasurer guide's gate section and the CLAUDE.md status log

**Files:**
- Modify: `core/docs/treasurer-guide.md` (the "Tuition & registration gates" section, roughly lines 292-345)
- Modify: `CLAUDE.md` (append a status bullet after the task #483 advisor-pool entry)

**Interfaces:**
- Consumes: the finished behavior from Tasks 1-3.
- Produces: nothing.

- [ ] **Step 1: Rewrite the treasurer guide's gate section**

`core/docs/treasurer-guide.md` currently documents two gates and a case table whose `committed` row says "Blocked by Gate 2", and which has no `plan_requested` row at all. This is rendered in the treasurer's Help tab, so it is the policy's user-facing statement.

Replace everything from the `## Tuition & registration gates` heading through the end of the "Full case table" section (up to but not including the `---` that precedes `## Payments tab`) with:

```markdown
## Tuition & registration gate

There is **one gate** in front of event registration for in-training
students. (It keys off a student's **tuition decision** for the year — money
doesn't drive it, the decision does.)

### A decision must be on file

An in-training student with no tuition decision recorded for the event's
academic year cannot register for *any* event. They see a polite page
directing them to `/tuition/`. **Any** decision clears this gate —
**including `skipping`**, and including a payment plan still awaiting the
Board. The point is to force engagement with the annual decision, not to
collect money.

### Coverage is per event, and every non-skipping decision gets it

Whether an event is covered by tuition is set **per event**, by whoever
configures its price tiers (a tier with "covered by tuition" checked,
matching the student's audience). Where such a tier exists, it applies to
every non-skipping decision: `committed`, `plan_requested`, `payment_plan`,
and `paid_in_full` alike. Where it doesn't, the student pays the regular fee
whatever their tuition status.

Until task #484 (2026-07-29) a second gate blocked a `committed`
student from a tuition-covered **special event**, on the grounds that they
would be claiming coverage they hadn't paid for. That gate is gone: the fee
is waived on the assumption tuition will be paid, and a plan application
pending with the Board is treated the same way rather than waiting on the
Board's turnaround.

### Full case table

Read as: *"a student with this tuition status, registering for this kind
of event, gets this outcome."*

| Tuition status | Any event with no covered tier for their audience | Any event with a covered tier matching their audience |
|---|---|---|
| **No decision recorded** | Blocked | Blocked |
| **`committed`** | Allowed — pays regular fee | Allowed — covered |
| **`plan_requested`** (with the Board) | Allowed — pays regular fee | Allowed — covered |
| **`payment_plan`** | Allowed — pays regular fee | Allowed — covered |
| **`paid_in_full`** | Allowed — pays regular fee | Allowed — covered |
| **`skipping`** | Allowed — pays regular fee | Allowed — pays regular fee (coverage doesn't apply to skipping) |

**Non-in-training roles** (Analyst, Scholar, Auditor) are never blocked by
the gate — they register on the regular rules: free where allowed, paid
where required.
```

Check the surrounding prose for stale cross-references: run `grep -n "Gate 1\|Gate 2\|two gates" core/docs/treasurer-guide.md` and fix any hit left over elsewhere in the file.

- [ ] **Step 2: Verify the doc still renders**

Run: `uv run pytest content/test_guides.py payments/test_treasurer_accounts.py -q`
Expected: PASS. `content/test_guides.py::test_all_listed_guides_render` is the one that actually exercises `render_doc` over the guide files, so a markdown mistake surfaces there.

Watch the rendered-markdown gotcha: no continuation line inside a list item or table cell may begin with `+`, `-`, or `*`. The block above already complies; keep it that way if you rewrap.

- [ ] **Step 3: Add the CLAUDE.md status entry**

In `CLAUDE.md`, append this bullet immediately after the task #483 entry ("**Advisor pool opened to all eligible analysts** (task #483)…") and before the "Milestones 7–8 then cover…" paragraph. In-repo docs use unspaced em dashes.

```markdown
- **A requested payment plan covers events** (task #484). Applying for a
  payment plan is a request to the Board (`PLAN_REQUESTED` + a PENDING
  `TuitionPlanApplication`, task #450 phase B), and fall registration could
  not wait on the Board's turnaround. The hold was never a *block* — the
  enrollment row exists, so the broad no-decision gate was always satisfied —
  it was **pricing**: `PLAN_REQUESTED` was absent from
  `TuitionEnrollment.covers_seminars`, so `is_tuition_current()` was False, no
  `covered_by_tuition` tier resolved, and the member was quoted the full
  seminar fee. The charge side never agreed with that reading:
  `payments.charges._owed_periods` exempts only SKIPPING, so the year's
  tuition charge was minted regardless — the school treated the money as owed
  while withholding what paying it buys. `covers_seminars` now covers every
  non-skipping decision. Second, the **narrow special-event gate is deleted**
  (`TUITION_BLOCKING_EVENT_TYPES` + its branch in `_tuition_block_reason`):
  per Rico (2026-07-29), a tuition-eligible special event is waived for
  COMMITTED *and* PLAN_REQUESTED on the assumption tuition will be paid, which
  removes the one place where "committed but no money yet" had teeth —
  deliberately, and reversible by revert rather than by a flag. One gate
  remains: some decision must be on file. Also: a fully covered year reads
  "Paid" for a pending request (`payments/ledger.py`), the member's pending
  note and the Board's queue intro both say coverage is already live, and the
  decline notification warns that a $0 registration taken under provisional
  coverage may need settling (nothing unwinds automatically — do-not-over-
  automate). No migration, no backfill, no flag; balances cannot move. Design:
  `docs/superpowers/specs/2026-07-29-plan-requested-seminar-coverage-design.md`.
```

- [ ] **Step 4: Run the full suite and the linter**

Run: `uv run pytest -q`
Expected: PASS, zero failures.

Run: `uv run ruff check .`
Expected: `All checks passed!`

If a failure appears in a suite this plan never touched, do not paper over it — read the test, and report it rather than editing an unrelated assertion to fit.

- [ ] **Step 5: Commit**

```bash
git add core/docs/treasurer-guide.md CLAUDE.md
git commit -m "docs: one registration gate, and coverage for a pending plan request (#484)"
```

---

## Verification

The change is behavioral and gate-shaped, so verify by the four states rather than by a single happy path. With the suite green, confirm:

1. `PLAN_REQUESTED` → covered tier resolves, no block (Task 1 + 2 tests).
2. `COMMITTED` on a covered special event → covered, no 403 (Task 2 test) — the deliberate policy widening.
3. `SKIPPING` → still no coverage, still pays, still not blocked (existing tests, untouched).
4. No enrollment row → still blocked from every event type (existing tests, untouched).

No prod data step is required: nothing is migrated or backfilled, and no obligation or balance can move. After merge, the deploy is the ordinary push-to-`main` path, and `pushed-is-not-deployed` applies — watch the Deploy run go green.
