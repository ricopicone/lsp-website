# Registration Eligibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the event edit form's guest option teeth — an event declares who may register (members only, or members and guests) and the site enforces it.

**Architecture:** `Event.open_to_guests` (a messaging-only boolean) becomes `Event.registration_eligibility`, a two-choice field. One predicate in `registrations/permissions.py` answers whether a user may register, and `registrations.views.register_for_event` is the single enforcement point, guarding beside the existing tuition gate. The event page, the login/signup funnel, and both edit forms follow the field.

**Tech Stack:** Django 5.2, pytest-django, Tailwind v4 + DaisyUI v5.

**Spec:** `docs/superpowers/specs/2026-08-12-registration-eligibility-design.md`

## Global Constraints

- A guest is anyone for whom `accounts.permissions.is_lsp_member(user)` is False. No second predicate.
- Default is `members_and_guests`; no live event changes behavior.
- Member-facing copy uses commas, not em dashes (`em-dash-prose-style`).
- Never add a per-page Django messages loop (`messages-render-once-in-base`).
- CSS classes set in Python must also appear in a template, or Tailwind strips them (`tailwind-classes-set-in-python`).
- The field stays out of `events.review.REVIEWABLE_FIELDS`.
- Run tests with `uv run pytest`; lint with `uv run ruff check .`.

---

### Task 1: The field and the data migration

**Files:**
- Modify: `events/models.py:507-514` (the `open_to_guests` field), plus a new `TextChoices` class beside `Visibility` (`events/models.py:343-345`)
- Create: `events/migrations/0048_registration_eligibility.py`
- Test: `events/tests.py:58-66`

**Interfaces:**
- Produces: `Event.RegistrationEligibility.MEMBERS_AND_GUESTS` (`"members_and_guests"`) and `.MEMBERS_ONLY` (`"members_only"`); `Event.registration_eligibility` (CharField, default `MEMBERS_AND_GUESTS`). Every later task consumes these.

- [ ] **Step 1: Replace the existing default test**

Replace `test_event_open_to_guests_defaults_true` in `events/tests.py` with:

```python
@pytest.mark.django_db
def test_registration_eligibility_defaults_to_members_and_guests():
    e = Event.objects.create(
        title="Special Evening",
        slug="special-evening",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 1),
    )
    assert e.registration_eligibility == Event.RegistrationEligibility.MEMBERS_AND_GUESTS
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest events/tests.py::test_registration_eligibility_defaults_to_members_and_guests -v`
Expected: FAIL, `AttributeError: type object 'Event' has no attribute 'RegistrationEligibility'`.

- [ ] **Step 3: Add the choices class and the field**

In `events/models.py`, beside the `Visibility` class:

```python
    class RegistrationEligibility(models.TextChoices):
        MEMBERS_AND_GUESTS = "members_and_guests", _("Members and guests")
        MEMBERS_ONLY = "members_only", _("Members only")
```

Replace the whole `open_to_guests` field with:

```python
    registration_eligibility = models.CharField(
        max_length=20,
        choices=RegistrationEligibility.choices,
        default=RegistrationEligibility.MEMBERS_AND_GUESTS,
        verbose_name="Who can register",
        help_text=(
            "Members only limits registration to members of the School. "
            "Members and guests lets anyone with a free account register, "
            "and shows a guests-welcome note on the event page."
        ),
    )
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations events -n registration_eligibility`
Expected: creates `events/migrations/0048_registration_eligibility.py` with an `AddField` and a `RemoveField`.

- [ ] **Step 5: Hand-add the data copy between them**

Edit the generated migration so the operations run in this order: `AddField`, then this `RunPython`, then `RemoveField`.

```python
def _copy_forward(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    Event.objects.filter(open_to_guests=False).update(
        registration_eligibility="members_only"
    )


def _copy_back(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    Event.objects.update(open_to_guests=True)
    Event.objects.filter(registration_eligibility="members_only").update(
        open_to_guests=False
    )
```

Wire it as `migrations.RunPython(_copy_forward, _copy_back)`. The `AddField` default already writes `members_and_guests` everywhere, so forward only needs to move the `False` rows.

- [ ] **Step 6: Run the test and the events suite**

Run: `uv run pytest events/tests.py -x -q`
Expected: the new test PASSES. Other tests referencing `open_to_guests` fail — Task 4 and Task 5 own those; leave them for now.

- [ ] **Step 7: Commit**

```bash
git add events/models.py events/migrations/0048_registration_eligibility.py events/tests.py
git commit -m "feat(events): registration_eligibility replaces open_to_guests (task #566)"
```

---

### Task 2: The eligibility predicate

**Files:**
- Modify: `registrations/permissions.py` (append)
- Test: `registrations/test_eligibility.py` (create)

**Interfaces:**
- Consumes: `Event.RegistrationEligibility` (Task 1).
- Produces: `registrations.permissions.eligibility_block_reason(user, event) -> str | None` — a member-facing reason, or `None` to allow. Task 3 and Task 4 consume it.

- [ ] **Step 1: Write the failing tests**

Create `registrations/test_eligibility.py`:

```python
"""Who may register: members only, or members and guests (task #566)."""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from accounts.models import Profile, User
from events.models import Event, PricingCode
from registrations.permissions import eligibility_block_reason


def _event(**kwargs):
    defaults = dict(
        title="Special Evening", slug="special-evening",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
        status=Event.Status.OPEN, published=True,
        registration_eligibility=Event.RegistrationEligibility.MEMBERS_ONLY,
    )
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def _user(email, role=Profile.Role.EXTERNAL, **profile_kwargs):
    user = User.objects.create_user(email=email, password="pw")
    Profile.objects.filter(pk=user.profile.pk).update(role=role, **profile_kwargs)
    user.profile.refresh_from_db()
    return user


@pytest.mark.django_db
def test_open_event_admits_anyone():
    event = _event(
        registration_eligibility=Event.RegistrationEligibility.MEMBERS_AND_GUESTS
    )
    assert eligibility_block_reason(_user("guest@example.org"), event) is None


@pytest.mark.django_db
def test_member_is_admitted():
    event = _event()
    assert eligibility_block_reason(_user("a@example.org", Profile.Role.ANALYST), event) is None


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["external", "student", "prospective_applicant"])
def test_every_non_member_role_is_blocked(role):
    event = _event()
    reason = eligibility_block_reason(_user(f"{role}@example.org", role), event)
    assert reason is not None
    assert "members of the Lacanian School" in reason


@pytest.mark.django_db
def test_resigned_member_is_blocked():
    event = _event()
    user = _user("gone@example.org", Profile.Role.ANALYST, standing=Profile.Standing.RESIGNED)
    assert eligibility_block_reason(user, event) is not None


@pytest.mark.django_db
def test_guest_with_a_code_addressed_to_them_is_admitted():
    event = _event()
    guest = _user("guest@example.org")
    faculty = _user("f@example.org", Profile.Role.ANALYST)
    PricingCode.objects.create(
        event=event, code="GUEST1", issued_by=faculty,
        pricing_mode=PricingCode.Mode.PERCENT_OFF, amount_or_percent=100,
        max_uses=1, uses_remaining=1, restricted_to_user=guest,
    )
    assert eligibility_block_reason(guest, event) is None


@pytest.mark.django_db
def test_an_unrestricted_code_does_not_open_the_door():
    event = _event()
    guest = _user("guest@example.org")
    faculty = _user("f@example.org", Profile.Role.ANALYST)
    PricingCode.objects.create(
        event=event, code="ANYONE", issued_by=faculty,
        pricing_mode=PricingCode.Mode.PERCENT_OFF, amount_or_percent=100,
        max_uses=1, uses_remaining=1,
    )
    assert eligibility_block_reason(guest, event) is not None


@pytest.mark.django_db
def test_a_spent_code_does_not_open_the_door():
    event = _event()
    guest = _user("guest@example.org")
    faculty = _user("f@example.org", Profile.Role.ANALYST)
    PricingCode.objects.create(
        event=event, code="SPENT", issued_by=faculty,
        pricing_mode=PricingCode.Mode.PERCENT_OFF, amount_or_percent=100,
        max_uses=1, uses_remaining=0, restricted_to_user=guest,
    )
    assert eligibility_block_reason(guest, event) is not None


@pytest.mark.django_db
def test_an_expired_code_does_not_open_the_door():
    event = _event()
    guest = _user("guest@example.org")
    faculty = _user("f@example.org", Profile.Role.ANALYST)
    PricingCode.objects.create(
        event=event, code="STALE", issued_by=faculty,
        pricing_mode=PricingCode.Mode.PERCENT_OFF, amount_or_percent=100,
        max_uses=1, uses_remaining=1, restricted_to_user=guest,
        valid_until=timezone.now() - timedelta(days=1),
    )
    assert eligibility_block_reason(guest, event) is not None


@pytest.mark.django_db
def test_an_outside_speaker_is_never_told_members_only():
    """A PC event's presenter with a linked login (task #463) presents at it."""
    event = _event()
    speaker_user = _user("speaker@example.org")
    event.member_speakers.add(speaker_user)
    assert eligibility_block_reason(speaker_user, event) is None


@pytest.mark.django_db
def test_anonymous_is_blocked():
    from django.contrib.auth.models import AnonymousUser

    assert eligibility_block_reason(AnonymousUser(), _event()) is not None
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest registrations/test_eligibility.py -q`
Expected: every test FAILS on `ImportError: cannot import name 'eligibility_block_reason'`.

Check as you go: confirm `Event.member_speakers` is the right M2M name for `test_an_outside_speaker_is_never_told_members_only` (`grep -n "member_speakers" events/models.py`). If `is_presenter` requires a PC-organized type, `SPECIAL_EVENT` already is one.

- [ ] **Step 3: Write the predicate**

Append to `registrations/permissions.py`:

```python
#: Shown to a guest who cannot register for a members-only event. Names the
#: restriction and both routes onward: the School's application, and the
#: faculty's own escape hatch, a code addressed to them (task #566).
MEMBERS_ONLY_REASON = (
    "Registration for this event is limited to members of the Lacanian "
    "School. If you have been invited to attend, ask the event's faculty "
    "for a registration code addressed to you."
)


def eligibility_block_reason(user, event) -> str | None:
    """Why ``user`` may not register for ``event``, or None to allow.

    Mirrors ``registrations.views._tuition_block_reason``: a member-facing
    string blocks, None admits.

    An event set to *Members only* admits members (the one definition,
    ``accounts.permissions.is_lsp_member``), anyone holding a live pricing
    code addressed to them by name (the faculty's own discretion, §4.1), and
    the people who run the event, so an outside speaker with a linked login
    is never told "members only" about their own evening.
    """
    from events.models import Event

    if event.registration_eligibility != Event.RegistrationEligibility.MEMBERS_ONLY:
        return None

    from accounts.permissions import is_lsp_member

    if is_lsp_member(user):
        return None
    if not getattr(user, "is_authenticated", False):
        return MEMBERS_ONLY_REASON

    from events.models import PricingCode

    for code in PricingCode.objects.filter(event=event, restricted_to_user=user):
        if code.is_redeemable(user=user):
            return None

    from events.permissions import can_edit_event

    if can_edit_event(user, event) or event.is_presenter(user):
        return None
    return MEMBERS_ONLY_REASON
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest registrations/test_eligibility.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add registrations/permissions.py registrations/test_eligibility.py
git commit -m "feat(registrations): eligibility_block_reason predicate (task #566)"
```

---

### Task 3: Enforce it in the register view

**Files:**
- Modify: `registrations/views.py:167-175` (beside the tuition gate)
- Create: `registrations/templates/registrations/blocked_members_only.html`
- Test: `registrations/test_eligibility.py` (append)

**Interfaces:**
- Consumes: `eligibility_block_reason` (Task 2).
- Produces: a 403 response rendering `registrations/blocked_members_only.html` with context `{"event": event, "reason": reason}`.

- [ ] **Step 1: Write the failing tests**

Append to `registrations/test_eligibility.py`:

```python
@pytest.mark.django_db
def test_guest_gets_403_at_the_register_url(client):
    event = _event()
    guest = _user("guest@example.org")
    client.force_login(guest)
    resp = client.get(f"/events/{event.slug}/register/")
    assert resp.status_code == 403
    assert "limited to members" in resp.content.decode()


@pytest.mark.django_db
def test_member_reaches_the_register_page(client):
    event = _event()
    client.force_login(_user("a@example.org", Profile.Role.ANALYST))
    resp = client.get(f"/events/{event.slug}/register/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_a_guest_who_already_registered_keeps_their_registration(client):
    """Restricting an event later must not strand someone already enrolled."""
    from events.models import Audience, PriceTier
    from registrations.models import Registration

    event = _event(
        registration_eligibility=Event.RegistrationEligibility.MEMBERS_AND_GUESTS
    )
    tier = PriceTier.objects.create(event=event, audience=Audience.ALL, base_amount=0)
    guest = _user("guest@example.org")
    reg = Registration.objects.create(
        user=guest, event=event, price_tier=tier, quoted_amount=0,
        status=Registration.Status.PAID,
    )
    Event.objects.filter(pk=event.pk).update(
        registration_eligibility=Event.RegistrationEligibility.MEMBERS_ONLY
    )
    client.force_login(guest)
    resp = client.get(f"/events/{event.slug}/register/")
    assert resp.status_code == 302
    assert str(reg.id) in resp.url
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest registrations/test_eligibility.py -q -k "register_url or reaches or already_registered"`
Expected: the 403 test FAILS with 200.

- [ ] **Step 3: Add the guard**

In `registrations/views.py`, immediately after the tuition-gate block (the `_tuition_block_reason` `if`), add:

```python
    # Eligibility gate (task #566) — a members-only event admits members, a
    # guest holding a code addressed to them, and the people running it.
    if (reason := eligibility_block_reason(request.user, event)) is not None:
        return render(
            request, "registrations/blocked_members_only.html",
            {"event": event, "reason": reason},
            status=403,
        )
```

Import at the top of the module: `from registrations.permissions import eligibility_block_reason`.

It sits *after* the already-registered short-circuit, so an existing registration still resolves.

- [ ] **Step 4: Write the block template**

Create `registrations/templates/registrations/blocked_members_only.html`, modelled on `blocked_tuition.html`:

```html
{% extends "core/base.html" %}
{% block title %}Members only · LSP{% endblock %}
{% block content %}
<div class="max-w-xl mx-auto space-y-6">

  <header class="space-y-2">
    <h1 class="font-serif text-3xl text-base-content">This event is for members</h1>
    <p class="text-sm text-base-content/70">{{ event.title }}</p>
  </header>

  <div class="rounded-lg border border-base-300 bg-base-200/40 p-5 space-y-3">
    <p>{{ reason }}</p>
    <p class="text-sm">
      <a href="{% url 'admissions:apply_start' %}" class="link link-primary">Apply to the School →</a>
    </p>
  </div>

  <p class="text-sm">
    <a href="{% url 'events:detail' event.slug %}" class="link link-hover text-base-content/70">← Back to the event</a>
  </p>

  <p class="text-sm text-base-content/60">
    Questions? Write to
    <a href="mailto:website@lacanschool.org" class="link">website@lacanschool.org</a>.
  </p>

</div>
{% endblock %}
```

Check the event-detail URL name before writing it: `grep -n "name=\"detail\"" events/urls.py`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest registrations/test_eligibility.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add registrations/views.py registrations/templates/registrations/blocked_members_only.html registrations/test_eligibility.py
git commit -m "feat(registrations): enforce members-only registration (task #566)"
```

---

### Task 4: The event page

**Files:**
- Modify: `events/templates/events/_event_summary.html:224-243` (the guest note and the Register CTA)
- Modify: `events/views.py` (the event-detail context builder — add `eligibility_reason`)
- Test: `events/tests.py:433-460` (rewrite the three guest-note tests), `registrations/test_eligibility.py` (append)

**Interfaces:**
- Consumes: `eligibility_block_reason` (Task 2).
- Produces: template context key `eligibility_reason` (str or None) on the event detail page.

- [ ] **Step 1: Rewrite the existing guest-note tests**

In `events/tests.py`, rename and update the three tests that reference `open_to_guests`:

```python
@pytest.mark.django_db
def test_event_page_shows_guest_note_when_open_to_guests(client):
    e = _special_event()
    content = client.get(f"/events/{e.slug}/").content.decode()
    assert "Guests are welcome" in content
    assert "create a free account" in content


@pytest.mark.django_db
def test_event_page_hides_guest_note_when_members_only(client):
    e = _special_event(
        registration_eligibility=Event.RegistrationEligibility.MEMBERS_ONLY
    )
    content = client.get(f"/events/{e.slug}/").content.decode()
    assert "Guests are welcome" not in content
```

- [ ] **Step 2: Add the CTA tests**

Append to `registrations/test_eligibility.py`:

```python
@pytest.mark.django_db
def test_event_page_drops_the_register_button_for_a_blocked_guest(client):
    event = _event()
    client.force_login(_user("guest@example.org"))
    content = client.get(f"/events/{event.slug}/").content.decode()
    assert 'id="register-cta"' not in content
    assert "limited to members" in content


@pytest.mark.django_db
def test_event_page_keeps_the_register_button_for_a_member(client):
    event = _event()
    client.force_login(_user("a@example.org", Profile.Role.ANALYST))
    assert 'id="register-cta"' in client.get(f"/events/{event.slug}/").content.decode()


@pytest.mark.django_db
def test_anonymous_visitor_keeps_the_button_with_a_note(client):
    """The site can't tell a signed-out member from a stranger, so it must not
    turn one away at the door."""
    event = _event()
    content = client.get(f"/events/{event.slug}/").content.decode()
    assert 'id="register-cta"' in content
    assert "limited to members" in content
```

- [ ] **Step 3: Run them and watch them fail**

Run: `uv run pytest registrations/test_eligibility.py -q -k "event_page or anonymous_visitor"`
Expected: FAIL — the button is present for the blocked guest and no note renders.

- [ ] **Step 4: Add the context key**

Find the event detail view (`grep -n "_event_summary\|def event_detail" events/views.py`) and add to its context:

```python
    from registrations.permissions import eligibility_block_reason

    context["eligibility_reason"] = (
        eligibility_block_reason(request.user, event)
        if request.user.is_authenticated else None
    )
```

Anonymous visitors get `None` deliberately: they keep the button and get the note from the template's own eligibility check.

- [ ] **Step 5: Update the CTA block**

Replace the registration CTA section of `events/templates/events/_event_summary.html` with:

```html
{# ---------- Registration CTA ---------- #}
<section class="pt-2">
  {% if event.status == "open" and event.is_public_now %}
    {% if user_registration %}
      <a href="{% url 'registrations:confirm' user_registration.id %}" class="btn btn-primary btn-lg">View your registration →</a>
    {% elif eligibility_reason %}
      <p class="text-base-content/80">{{ eligibility_reason }}</p>
      <p class="text-sm mt-2">
        <a href="{% url 'admissions:apply_start' %}" class="link link-primary">Apply to the School →</a>
      </p>
    {% else %}
      <a href="{% url 'registrations:register' event.slug %}" id="register-cta" class="btn btn-primary btn-lg">Register →</a>
      {% if event.registration_eligibility == "members_only" %}
      <p class="text-sm text-base-content/70 mt-2">Registration for this event is limited to members of the School.</p>
      {% elif not user_registration %}
      <p class="text-sm text-base-content/70 mt-2">Open to non-members. Guests are welcome to attend.</p>
      {% if not user.is_authenticated %}
      <p class="text-sm text-base-content/60">You'll be asked to sign in or create a free account. You don't need to be a member.</p>
      {% endif %}
      {% endif %}
    {% endif %}
  {% elif event.status == "draft" %}
    <p class="text-base-content/60">Registration not yet open.</p>
  {% elif event.status == "closed" %}
    <p class="text-base-content/60">Registration is closed.</p>
  {% endif %}
</section>
```

The old `event.visibility != "members_only"` conjunction goes: eligibility alone drives the note now.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest registrations/test_eligibility.py events/tests.py -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add events/templates/events/_event_summary.html events/views.py events/tests.py registrations/test_eligibility.py
git commit -m "feat(events): event page follows registration eligibility (task #566)"
```

---

### Task 5: Both edit forms

**Files:**
- Modify: `events/forms.py:168` (`EventEditForm.Meta.fields`), `events/forms.py:763` and `:795` (`ProgramEventForm`)
- Modify: `events/templates/events/event_edit.html:111-117`
- Modify: `events/templates/events/program_admin/event_form.html:147-155`
- Test: `events/tests.py:384-418`

**Interfaces:**
- Consumes: `Event.registration_eligibility` (Task 1).

- [ ] **Step 1: Rewrite the two form tests**

In `events/tests.py`, replace `test_open_to_guests_is_on_edit_forms_and_not_reviewable` and `test_staff_edit_toggles_open_to_guests_immediately`:

```python
def test_registration_eligibility_is_on_edit_forms_and_not_reviewable():
    from events.forms import EventEditForm, ProgramEventForm
    from events.review import REVIEWABLE_FIELDS

    assert "registration_eligibility" in EventEditForm.Meta.fields
    assert "registration_eligibility" in ProgramEventForm.Meta.fields
    # Non-reviewable: applies immediately, skips the change-review dialog.
    assert "registration_eligibility" not in REVIEWABLE_FIELDS


@pytest.mark.django_db
def test_staff_edit_sets_registration_eligibility_immediately(client):
    staff = User.objects.create_user(
        email="staff@example.org", password="pw", is_staff=True
    )
    e = Event.objects.create(
        title="Special Evening", slug="special-evening",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
        status=Event.Status.OPEN, published=True,
    )
    client.force_login(staff)
    resp = client.post(f"/events/{e.slug}/edit/", {
        "title": e.title,
        "description": "",
        "readings": "",
        "schedule_note": "",
        "contact": "",
        "fee_note": "",
        "registration_eligibility": "members_only",
    })
    assert resp.status_code == 302
    e.refresh_from_db()
    assert e.registration_eligibility == Event.RegistrationEligibility.MEMBERS_ONLY
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest events/tests.py -q -k "registration_eligibility"`
Expected: FAIL on the `Meta.fields` assertion.

- [ ] **Step 3: Swap the field in both forms**

In `events/forms.py`, replace `"open_to_guests"` with `"registration_eligibility"` in both `Meta.fields` tuples. Replace the `ProgramEventForm` widget entry with:

```python
            "registration_eligibility": forms.Select(
                attrs={"class": "select select-bordered w-full"},
            ),
```

Add the same widget to `EventEditForm.Meta.widgets`.

Because it is a `CharField` with a default, a POST that omits it would fail validation where the old checkbox silently read False. Guard it the way `ce_credits_basis` is guarded, in `EventEditForm.__init__` and `ProgramEventForm.__init__`:

```python
        self.fields["registration_eligibility"].required = False
```

and coerce in each form (`new-modelform-field-is-required-by-default`):

```python
    def clean_registration_eligibility(self):
        return (
            self.cleaned_data.get("registration_eligibility")
            or Event.RegistrationEligibility.MEMBERS_AND_GUESTS
        )
```

- [ ] **Step 4: Update the faculty edit template**

Replace the `open_to_guests` label block in `events/templates/events/event_edit.html` with:

```html
    <div class="space-y-1">
      <label class="label-text" for="{{ form.registration_eligibility.id_for_label }}">Who can register</label>
      {{ form.registration_eligibility }}
      <p class="text-xs text-base-content/60">
        Members only limits registration to members of the School. Members and
        guests lets anyone with a free account register, and shows a
        guests-welcome note on the event page.
      </p>
      {% if form.registration_eligibility.errors %}<p class="text-error text-xs">{{ form.registration_eligibility.errors|join:", " }}</p>{% endif %}
    </div>
```

- [ ] **Step 5: Update the PC template**

Replace the `open_to_guests` block in `events/templates/events/program_admin/event_form.html` with:

```html
      <div class="space-y-1">
        <label class="text-sm" for="{{ form.registration_eligibility.id_for_label }}">Who can register</label>
        {{ form.registration_eligibility }}
        <p class="text-xs text-base-content/50">{{ form.registration_eligibility.help_text }}</p>
        {% if form.registration_eligibility.errors %}<p class="text-error text-xs">{{ form.registration_eligibility.errors|join:", " }}</p>{% endif %}
      </div>
```

- [ ] **Step 6: Pin the change-review re-post**

The confirm dialog (`events/templates/events/event_edit_confirm.html:36-42`) carries non-reviewable fields forward as hidden `<textarea>`s. A select survives that where a checkbox needs a special case; a silent revert is the failure mode, so pin it. Append to `events/tests.py`:

```python
@pytest.mark.django_db
def test_eligibility_survives_the_change_review_repost(client):
    """A hidden <textarea> carries the select's value; a silent revert here
    would undo an eligibility change on any reviewed event (task #566)."""
    from events.forms import EventEditForm

    e = Event.objects.create(
        title="Reviewed Seminar", slug="reviewed-seminar",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
        status=Event.Status.OPEN, published=True,
    )
    form = EventEditForm(
        data={
            "title": e.title, "description": "", "readings": "",
            "schedule_note": "", "contact": "", "fee_note": "",
            "registration_eligibility": "members_only",
        },
        instance=e,
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["registration_eligibility"] == "members_only"
```

- [ ] **Step 7: Run the events suite**

Run: `uv run pytest events/ -q`
Expected: all PASS. `grep -rn "open_to_guests" events/ registrations/ accounts/` should now return nothing.

- [ ] **Step 8: Commit**

```bash
git add events/forms.py events/templates/events/event_edit.html events/templates/events/program_admin/event_form.html events/tests.py
git commit -m "feat(events): who-can-register control on both edit forms (task #566)"
```

---

### Task 6: The login and signup funnel

**Files:**
- Modify: `accounts/templates/registration/login.html:59`
- Modify: `accounts/templates/registration/signup.html:13`
- Test: `accounts/tests.py` or the file holding the task #464 funnel tests (find with `grep -rn "register_event" accounts/test*.py`)

**Interfaces:**
- Consumes: `register_event` (already in both templates' context via `accounts.views._register_event_from_next`) and `Event.registration_eligibility` (Task 1).

- [ ] **Step 1: Write the failing test**

Add to the funnel's test file:

```python
@pytest.mark.django_db
def test_login_funnel_does_not_promise_entry_to_a_members_only_event(client):
    from events.models import Event

    e = Event.objects.create(
        title="Members Evening", slug="members-evening",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
        status=Event.Status.OPEN, published=True,
        registration_eligibility=Event.RegistrationEligibility.MEMBERS_ONLY,
    )
    content = client.get(
        f"/accounts/login/?next=/events/{e.slug}/register/"
    ).content.decode()
    assert "You don&#x27;t need to be a member" not in content
    assert "limited to members" in content
```

Note the HTML-escaped apostrophe (`test-assertion-traps-in-this-repo`).

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest <that file> -q -k members_only`
Expected: FAIL — the unconditional line is present.

- [ ] **Step 3: Make login's promise conditional**

In `accounts/templates/registration/login.html`, replace the closing paragraph:

```html
  {% if register_event and register_event.registration_eligibility == "members_only" %}
  <p class="text-xs text-base-content/60 text-center">Registration for that event is limited to members of the School. An account is still free, and you can use one for other events.</p>
  {% else %}
  <p class="text-xs text-base-content/60 text-center">Anyone can create a free account. You don't need to be a member{% if register_event %} to attend{% endif %}.</p>
  {% endif %}
```

- [ ] **Step 4: Do the same on signup**

In `accounts/templates/registration/signup.html`, the header paragraph gains the same fork — keep the existing sentence, and for a members-only `register_event` add a preceding line:

```html
    {% if register_event and register_event.registration_eligibility == "members_only" %}
    <p class="text-sm text-base-content/70">Registration for {{ register_event.title }} is limited to members of the School.</p>
    {% endif %}
```

- [ ] **Step 5: Run the accounts tests**

Run: `uv run pytest accounts/ -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add accounts/templates/registration/login.html accounts/templates/registration/signup.html <test file>
git commit -m "feat(accounts): auth funnel stops promising entry to members-only events (task #566)"
```

---

### Task 7: Documentation and the status log

**Files:**
- Modify: `content/pages/guides/faculty.md:118-131` (the "For someone outside the School" section)
- Modify: `core/docs/registrar-guide.md`
- Modify: `docs/event-video-rehearsal.md:41`
- Modify: `CLAUDE.md` (status log entry)

- [ ] **Step 1: Narrow the faculty guide's outsider recipe**

In `content/pages/guides/faculty.md`, under "For someone outside the School", after the two bullets, add:

```markdown
**If the event is set to Members only**, the code has to be pinned to them, so
they need an account first. Ask them to create one, then pick them under *Only
this person may use it*. An unrestricted code won't get a guest in, because a
code that can be forwarded isn't a decision about a person.
```

Mind the rendered-markdown gotcha: never start a wrapped line inside a list item with `+`, `-`, or `*`.

- [ ] **Step 2: Note it in the registrar guide**

Add a short paragraph to `core/docs/registrar-guide.md` near the comp action: comping is unaffected by an event's eligibility setting, so the registrar can always seat someone by hand.

- [ ] **Step 3: Update the rehearsal checklist**

In `docs/event-video-rehearsal.md`, change the `open_to_guests` row to `registration_eligibility`.

- [ ] **Step 4: Add the CLAUDE.md status entry**

Append a status-log bullet in the house style, covering: what the flag was, what it now does, that a guest is `is_lsp_member`'s complement, that a code addressed by name is the escape hatch and an unrestricted one is not, that anonymous visitors keep the button, and that no live event changed.

- [ ] **Step 5: Run the docs tests**

Run: `uv run pytest content/ core/test_templates.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add content/pages/guides/faculty.md core/docs/registrar-guide.md docs/event-video-rehearsal.md CLAUDE.md
git commit -m "docs: registration eligibility (task #566)"
```

---

### Task 8: Full suite, lint, and ship

- [ ] **Step 1: Whole suite**

Run: `uv run pytest -q`
Expected: green. Any failure mentioning `open_to_guests` is a missed reference — fix it.

- [ ] **Step 2: Lint**

Run: `uv run ruff check .`
Expected: clean.

- [ ] **Step 3: Check the CSS build picks up nothing new**

The plan adds no Python-set CSS classes; the select's classes appear in templates. Confirm with `grep -rn "select select-bordered" events/templates | head -3`.

- [ ] **Step 4: Merge and push**

```bash
git checkout main && git merge --no-ff jade-falcon -m "Merge jade-falcon: registration eligibility has teeth (task #566)" && git push origin main
```

- [ ] **Step 5: Verify the deploy goes green**

`pushed-is-not-deployed`: a single failing test aborts the deploy silently. Watch the run with `gh run list --workflow Deploy --limit 3` until it reports success on this SHA.

## Self-Review

**Spec coverage:** field + migration (T1), predicate with all four permits (T2), single enforcement point + block page + existing-registration safety (T3), event page CTA and note including the anonymous case (T4), both forms + non-reviewable + re-post pin (T5), auth funnel copy (T6), all three docs (T7), suite/lint/deploy (T8). The spec's "staff paths untouched" needs no task: the registrar console and admin never call the view.

**Placeholders:** none — every step carries its code. Two steps ask for a `grep` to confirm a name (`Event.member_speakers`, the event-detail URL name, the funnel test file) rather than guessing; those are verifications, not gaps.

**Type consistency:** `eligibility_block_reason(user, event) -> str | None` is used identically in T3 and T4; `MEMBERS_ONLY_REASON` contains "limited to members of the Lacanian School", which every substring assertion matches on "limited to members"; the field name `registration_eligibility` and the two values are spelled the same throughout.
