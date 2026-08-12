# Registration-Approval Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Event.requires_faculty_approval` safe and honest to flip on a running seminar — grandfathering pinned by test, unticking releases the queue, faculty and conveners own the switch and hear about the queue, and members are told before they register.

**Architecture:** One new service (`release_pending_approvals`) beside `comp_registration`; one new permission helper (`offering_leads`) beside `_leads_offering`; the flag joins the faculty edit form with its change-review re-post exception; a rendered-when-on line on three member surfaces.

**Tech Stack:** Django 5.2, pytest-django, Tailwind v4 + DaisyUI v5.

**Spec:** `docs/superpowers/specs/2026-08-12-registration-approval-toggle-design.md`

## Global Constraints

- Member-facing copy says what happens, not why; commas rather than em dashes.
- DaisyUI semantic tokens only (`text-base-content/60`, `alert-info`), never `bg-gray-100`.
- `requires_faculty_approval` must NOT enter `events/review.py::REVIEWABLE_FIELDS`.
- The disclosure sentence, verbatim, everywhere it appears:
  `Registration for this seminar is reviewed by the faculty before it's confirmed.`
- Run `uv run pytest` and `uv run ruff check .` before the final push.

---

### Task 1: Pin the grandfathering

**Files:**
- Test: `registrations/test_approval.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing — a characterization test that locks current behaviour before anything else changes it.

- [ ] **Step 1: Write the test**

Append to `registrations/test_approval.py`, reusing the module's existing
`_event` / registration helpers (read the top of the file first and match them):

```python
@pytest.mark.django_db
def test_turning_approval_on_leaves_existing_registrations_alone(client):
    event = _approval_event(requires_faculty_approval=False)
    tier = event.price_tiers.first()
    early = Registration.objects.create(
        user=_member("early@example.com"), event=event, price_tier=tier,
        quoted_amount=Decimal("50"), status=Registration.Status.AWAITING_PAYMENT,
    )
    paid = Registration.objects.create(
        user=_member("paid@example.com"), event=event, price_tier=tier,
        quoted_amount=Decimal("50"), status=Registration.Status.PAID,
    )

    event.requires_faculty_approval = True
    event.save(update_fields=("requires_faculty_approval",))

    early.refresh_from_db()
    paid.refresh_from_db()
    assert early.status == Registration.Status.AWAITING_PAYMENT
    assert paid.status == Registration.Status.PAID

    later = _register(client, "later@example.com", event)
    assert later.status == Registration.Status.PENDING_APPROVAL
```

- [ ] **Step 2: Run it**

Run: `uv run pytest registrations/test_approval.py -k grandfather -v` (adjust
`-k` to the name you gave it).
Expected: PASS immediately — this documents behaviour that already holds.

- [ ] **Step 3: Commit**

```bash
git add registrations/test_approval.py
git commit -m "test(registrations): pin that turning approval on grandfathers existing registrations (task #564)"
```

---

### Task 2: `offering_leads` — who runs the offering

**Files:**
- Modify: `events/permissions.py` (beside `_leads_offering`, line ~19)
- Test: `events/tests.py`

**Interfaces:**
- Produces: `events.permissions.offering_leads(event) -> list[User]` — the
  event's faculty, then any additional serving lead-role members of the
  offering's own workgroup, deduped, order preserved.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_offering_leads_includes_reading_group_conveners():
    from events.permissions import offering_leads
    from workgroups.models import WorkgroupMembership

    event = _event(event_type=Event.Type.READING_GROUP)   # has a workgroup
    convener = _user("convener@example.com")
    WorkgroupMembership.objects.create(
        workgroup=event.workgroup, user=convener,
        role=WorkgroupMembership.Role.ORGANIZER,
    )

    assert convener in offering_leads(event)
    assert convener not in event.faculty_members()
```

- [ ] **Step 2: Run it**

Run: `uv run pytest events/tests.py -k offering_leads -v`
Expected: FAIL — `ImportError: cannot import name 'offering_leads'`.

- [ ] **Step 3: Implement**

In `events/permissions.py`:

```python
def offering_leads(event) -> list:
    """Everyone who runs this offering: its faculty, plus the lead-role members
    of its own workgroup for the types where leading the group *is* running the
    offering (a reading group's conveners hold ORGANIZER, not FACULTY — #495).

    This is the notification audience for anything that asks the people
    running an event to act. ``Event.faculty_members()`` answers a different
    question — who teaches it — and drives bylines and the roster, so it stays
    as it is.
    """
    people = list(event.faculty_members())
    if event.event_type in LEAD_LED_EVENT_TYPES and event.workgroup_id:
        seen = {u.pk for u in people}
        for m in event.workgroup.memberships.serving().filter(
            role__in=WorkgroupMembership.LEAD_ROLES,
        ).select_related("user"):
            if m.user.pk not in seen:
                seen.add(m.user.pk)
                people.append(m.user)
    return people
```

- [ ] **Step 4: Run it**

Run: `uv run pytest events/tests.py -k offering_leads -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add events/permissions.py events/tests.py
git commit -m "feat(events): offering_leads() — conveners run the offering too (task #564)"
```

---

### Task 3: Notify the conveners, and land the bell on the roster

**Files:**
- Modify: `payments/emails.py:287-301` (`_faculty_recipients`, `_faculty_tools_url`)
- Modify: `payments/notifications.py:189-201` (`registration_pending`)
- Modify: `payments/emails.py` (`send_approval_reminder` recipients — grep for it)
- Test: `registrations/test_approval.py`

**Interfaces:**
- Consumes: `events.permissions.offering_leads` (Task 2).
- Produces: `payments.emails.faculty_tools_url(event) -> str` (renamed from
  `_faculty_tools_url`; absolute URL to where approvals happen).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_pending_notice_reaches_conveners_and_links_to_the_roster(mailoutbox):
    from notifications.models import Notification
    from payments import notifications as notify_payments

    event = _approval_event(event_type=Event.Type.READING_GROUP)
    convener = _convener_of(event)          # ORGANIZER on event.workgroup
    reg = _pending_registration(event)

    notify_payments.registration_pending(reg)

    assert convener.email in mailoutbox[0].to
    bell = Notification.objects.get(user=convener)
    assert bell.url.endswith("?tab=roster")
```

- [ ] **Step 2: Run it**

Run: `uv run pytest registrations/test_approval.py -k conveners -v`
Expected: FAIL — the convener gets neither the mail nor a bell row.

- [ ] **Step 3: Implement**

In `payments/emails.py`, rename `_faculty_tools_url` → `faculty_tools_url`
(update its callers in this file), and swap the recipient helper's source:

```python
def _faculty_recipients(event) -> list[str]:
    """Emails of whoever runs the offering; falls back to support so nothing
    is lost."""
    from events.permissions import offering_leads
    emails = [u.email for u in offering_leads(event) if u.email]
    return emails or [settings.SUPPORT_EMAIL]
```

In `payments/notifications.py::registration_pending`, replace the hardcoded URL
and the recipient loop:

```python
def registration_pending(reg) -> None:
    """Tell whoever runs the offering that a registration needs approval. The
    batched email is unchanged; each of them also gets a bell row."""
    from events.permissions import offering_leads

    event = reg.event
    who = reg.user.get_full_name() or reg.user.email
    # An offering's event page redirects to its Workspace and drops the query
    # string, so ``?view=faculty`` landed faculty on Overview with no approve
    # buttons. This is the same URL the email already used.
    url = emails.faculty_tools_url(event).removeprefix(settings.SITE_BASE_URL)
    for lead in offering_leads(event):
        notify(
            lead, Category.REGISTRATION_STATUS,
            title=f"Approval needed: {who} — {event.title}",
            url=url, target=reg, email=False, dedupe=True,
        )
    emails.send_registration_pending_notice(reg)
```

Add the `settings` import if `payments/notifications.py` lacks one. Apply the
same `offering_leads` swap wherever `send_approval_reminder` builds its
recipients.

- [ ] **Step 4: Run it**

Run: `uv run pytest registrations/ payments/ -k "conveners or approval" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add payments/emails.py payments/notifications.py registrations/test_approval.py
git commit -m "fix(payments): approval notices reach conveners and link to the roster tab (task #564)"
```

---

### Task 4: Unticking releases the queue

**Files:**
- Modify: `registrations/services.py` (append beside `comp_registration`)
- Test: `registrations/test_approval.py`

**Interfaces:**
- Produces: `registrations.services.release_pending_approvals(event, by) -> list[Registration]`
  — approves every `PENDING_APPROVAL` row on `event`, notifies each member, and
  returns the rows it released (empty list when there were none).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_release_approves_pending_and_routes_on_amount():
    from registrations.services import release_pending_approvals

    event = _approval_event()
    free = _pending_registration(event, amount=Decimal("0"))
    owing = _pending_registration(event, amount=Decimal("50"))
    staff = _user("pc@example.com")

    released = release_pending_approvals(event, staff)

    assert {r.pk for r in released} == {free.pk, owing.pk}
    free.refresh_from_db(); owing.refresh_from_db()
    assert free.status == Registration.Status.PAID
    assert owing.status == Registration.Status.AWAITING_PAYMENT
    assert owing.approved_by == staff and owing.decided_at is not None
    assert release_pending_approvals(event, staff) == []   # idempotent
```

- [ ] **Step 2: Run it**

Run: `uv run pytest registrations/test_approval.py -k release -v`
Expected: FAIL — `ImportError: cannot import name 'release_pending_approvals'`.

- [ ] **Step 3: Implement**

Append to `registrations/services.py`:

```python
def release_pending_approvals(reg_event, by) -> list[Registration]:
    """Approve everything still waiting on an event (task #564).

    Called when ``requires_faculty_approval`` is turned back off: off has to be
    the inverse of on, or a queue nobody has a reason to hold keeps nudging the
    faculty every three days and has to be cleared one row at a time.

    Same side-effect chain as ``registrations.views.approve_registration``, so
    the two cannot drift. Returns the rows it released — build any message from
    these, not from a copy read before the call. Idempotent: ``approve()``
    returns False on a row that is no longer pending, so a second pass sends
    nothing.
    """
    released = []
    for reg in reg_event.registrations.filter(
        status=Registration.Status.PENDING_APPROVAL
    ).select_related("user", "event"):
        if not reg.approve(by):
            continue
        if reg.needs_payment:
            notify_payments.registration_approved(reg)
        else:
            notify_payments.registration_confirmed(reg)
        released.append(reg)
    return released
```

- [ ] **Step 4: Run it**

Run: `uv run pytest registrations/test_approval.py -k release -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add registrations/services.py registrations/test_approval.py
git commit -m "feat(registrations): release_pending_approvals() (task #564)"
```

---

### Task 5: Wire the release into both edit views

**Files:**
- Modify: `events/views.py:381` (`event_edit` — snapshot) and its two save paths
- Modify: `events/views.py:968-990` (`program_admin_event_edit`)
- Test: `events/tests.py`

**Interfaces:**
- Consumes: `registrations.services.release_pending_approvals` (Task 4).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_pc_form_unticking_approval_releases_the_queue(client):
    event = _approval_event(program=_program())
    pending = _pending_registration(event, amount=Decimal("50"))
    client.force_login(_pc_member())

    client.post(
        reverse("program_admin_event_edit", args=[event.program.academic_year, event.slug]),
        _program_event_post(event, requires_faculty_approval=""),   # unticked
    )

    pending.refresh_from_db()
    assert pending.status == Registration.Status.AWAITING_PAYMENT


@pytest.mark.django_db
def test_ticking_approval_on_releases_nothing(client):
    event = _approval_event(program=_program(), requires_faculty_approval=False)
    pending = _pending_registration(event, amount=Decimal("50"))
    client.force_login(_pc_member())

    client.post(
        reverse("program_admin_event_edit", args=[event.program.academic_year, event.slug]),
        _program_event_post(event, requires_faculty_approval="on"),
    )

    pending.refresh_from_db()
    assert pending.status == Registration.Status.PENDING_APPROVAL
```

- [ ] **Step 2: Run it**

Run: `uv run pytest events/tests.py -k "releases" -v`
Expected: FAIL — the pending row is untouched by the untick.

- [ ] **Step 3: Implement**

Add a shared helper near the top of `events/views.py`:

```python
def _release_if_approval_turned_off(request, event, was_required: bool) -> None:
    """Off is the inverse of on: unticking approval clears the queue it held.

    ``was_required`` MUST be read before the form is bound — ModelForm
    validation mutates the instance in place, so reading it afterwards compares
    the new value against itself (the bug that made ``changed_reviewable_fields``
    silently wrong in #532).
    """
    if not (was_required and not event.requires_faculty_approval):
        return
    from registrations.services import release_pending_approvals
    released = release_pending_approvals(event, request.user)
    if released:
        messages.success(request, (
            f"Approval turned off. {len(released)} registration"
            f"{'' if len(released) == 1 else 's'} waiting "
            f"{'was' if len(released) == 1 else 'were'} approved and notified."
        ))
```

In `program_admin_event_edit`, capture before binding and call after saving:

```python
    if request.method == "POST":
        was_required = event.requires_faculty_approval      # before binding
        form = ProgramEventForm(request.POST, instance=event, program=program)
        if form.is_valid():
            form.save_price(form.save())
            _release_if_approval_turned_off(request, event, was_required)
            return redirect(...)
```

In `event_edit`, capture `was_required = event.requires_faculty_approval`
immediately after the `if request.method != "POST"` block returns (i.e. beside
the existing `original = {...}` snapshot at line ~381), then call the helper in
**both** save paths: after `form.save()` in the straight-through branch, and
after the non-reviewable fields are applied in the decision branch.

- [ ] **Step 4: Run it**

Run: `uv run pytest events/tests.py -k "releases" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add events/views.py events/tests.py
git commit -m "feat(events): unticking approval on either edit form releases the queue (task #564)"
```

---

### Task 6: Faculty own the switch

**Files:**
- Modify: `events/forms.py:157-190` (`EventEditForm.Meta.fields` + widget)
- Modify: `events/templates/events/event_edit.html` (checkbox, near `record_video`)
- Modify: `events/templates/events/event_edit_confirm.html:36` (re-post exception)
- Test: `events/tests.py`

**Interfaces:**
- Consumes: Task 5's release wiring (already live on `event_edit`).

- [ ] **Step 1: Write the failing tests**

```python
def test_faculty_form_carries_the_approval_toggle():
    from events.forms import EventEditForm
    from events.review import REVIEWABLE_FIELDS

    assert "requires_faculty_approval" in EventEditForm.Meta.fields
    # Review protects content the PC approved; who may enrol is not that.
    assert "requires_faculty_approval" not in REVIEWABLE_FIELDS


def test_confirm_dialog_reposts_the_approval_checkbox():
    """A checkbox re-posted as a hidden <textarea> is silently dropped — it must
    follow the record_video precedent (#504, #532)."""
    src = Path("events/templates/events/event_edit_confirm.html").read_text()
    assert "requires_faculty_approval" in src
```

- [ ] **Step 2: Run them**

Run: `uv run pytest events/tests.py -k "approval_toggle or reposts" -v`
Expected: FAIL on both.

- [ ] **Step 3: Implement**

Add `"requires_faculty_approval"` to `EventEditForm.Meta.fields` (after
`"record_video"`). No widget entry needed — a model `BooleanField` is already
`blank=True`, so the form field is `required=False`.

In `event_edit_confirm.html:36`, extend the exception:

```django
{% if field.name == "record_video" or field.name == "tuition_covers" or field.name == "requires_faculty_approval" %}
```

In `event_edit.html`, beside the `record_video` checkbox:

```django
<label class="flex items-start gap-3 cursor-pointer">
  {{ form.requires_faculty_approval }}
  <span class="text-sm">Review each registration before it's confirmed
    <span class="block text-xs text-base-content/60">New registrations wait for your approval on the Roster tab. Anyone already registered keeps their place. Unticking this approves everyone still waiting.</span>
  </span>
</label>
```

- [ ] **Step 4: Run them**

Run: `uv run pytest events/ -k "approval_toggle or reposts" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add events/forms.py events/templates/events/event_edit.html events/templates/events/event_edit_confirm.html events/tests.py
git commit -m "feat(events): faculty and conveners can toggle registration approval (task #564)"
```

---

### Task 7: Tell members before they register

**Files:**
- Modify: `events/templates/events/_event_summary.html:232` (beside the CTA)
- Modify: `registrations/templates/registrations/register.html` (under the header)
- Modify: `registrations/templates/registrations/register_covered.html` (under the header)
- Test: `registrations/test_approval.py`

- [ ] **Step 1: Write the failing test**

```python
NOTICE = "reviewed by the faculty before it's confirmed"

@pytest.mark.django_db
def test_register_page_discloses_approval(client):
    event = _approval_event(requires_faculty_approval=True)
    client.force_login(_member("someone@example.com"))
    assert NOTICE in client.get(
        reverse("registrations:register", args=[event.slug])
    ).content.decode()


@pytest.mark.django_db
def test_register_page_silent_without_approval(client):
    event = _approval_event(requires_faculty_approval=False)
    client.force_login(_member("someone@example.com"))
    assert NOTICE not in client.get(
        reverse("registrations:register", args=[event.slug])
    ).content.decode()
```

- [ ] **Step 2: Run them**

Run: `uv run pytest registrations/test_approval.py -k discloses -v`
Expected: FAIL on the first.

- [ ] **Step 3: Implement**

In each of the three templates, at the natural top-of-content position:

```django
{% if event.requires_faculty_approval %}
<div role="alert" class="alert alert-info">
  <span>Registration for this seminar is reviewed by the faculty before it's confirmed.</span>
</div>
{% endif %}
```

On `_event_summary.html` put it directly under the `#register-cta` block, not
above the fold.

- [ ] **Step 4: Run them**

Run: `uv run pytest registrations/ events/ -k "discloses or silent" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add events/templates registrations/templates registrations/test_approval.py
git commit -m "feat(registrations): tell members when an event's registrations are reviewed (task #564)"
```

---

### Task 8: Help text, guide, docs, ship

**Files:**
- Modify: `events/models.py:491-497` (`help_text`) + a migration
- Modify: `events/templates/events/program_admin/event_form.html:135` area
- Modify: the faculty guide (grep `core/docs/` for the approvals section)
- Modify: `CLAUDE.md` (status log entry)

- [ ] **Step 1: Rewrite the help text**

```python
    requires_faculty_approval = models.BooleanField(
        default=False,
        help_text=(
            "If set, each new registration waits for the event's faculty (or a "
            "reading group's conveners) to approve it. Anyone already "
            "registered keeps their place; unsetting it approves everyone "
            "still waiting."
        ),
    )
```

- [ ] **Step 2: Make the migration**

Run: `uv run python manage.py makemigrations events`
Expected: one `AlterField` migration. Commit it with the model change.

- [ ] **Step 3: Update the faculty guide**

Grep `core/docs/` for the guide's approvals section (linked from
`_faculty_tools.html:7`) and add a short paragraph: where the switch is now, that
it only affects new registrations, and that turning it off approves whoever is
waiting. Remember the rendered-markdown gotcha — a `-` starting a wrapped line
inside a list item becomes a nested bullet.

- [ ] **Step 4: Full suite + lint**

Run: `uv run pytest` then `uv run ruff check .`
Expected: all green. Do not push on a single failure — a failing test silently
aborts the deploy.

- [ ] **Step 5: Status log + ship**

Add the task #564 entry to `CLAUDE.md`'s Status section in house style (what was
wrong, what changed, what was deliberately not done). Then merge to `main`, push,
and watch the Deploy run go green — pushed is not deployed.

```bash
git add -A && git commit -m "docs(core): record task #564 in the status log"
```

- [ ] **Step 6: Verify on prod**

Confirm no pre-existing `REGISTRATION_STATUS` bell rows point at
`?view=faculty` (the spec expects none, since no event has ever carried the
flag) — via SSM, `Notification.objects.filter(url__contains="view=faculty").count()`.
If any exist, repair them with a data migration (`notification-url-denormalized`).
