# Guest-Friendly Event Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make event registration welcoming to guests (non-members): a per-event `open_to_guests` flag with on-page messaging, context-aware login/signup pages when arriving from a Register click, and guest-friendly copy on the general auth surfaces.

**Architecture:** Pure Django server-rendered changes. One new boolean on `events.Event` (messaging-only, never gates registration), template copy in the shared event-summary partial, a thin `LoginView` subclass + shared `next`-resolution helper in `accounts`, and copy edits to the login/signup templates and site header.

**Tech Stack:** Django 5.2, pytest-django, Tailwind v4 + DaisyUI v5 (semantic tokens only).

**Spec:** `docs/superpowers/specs/2026-07-24-guest-event-registration-design.md`

## Global Constraints

- **Work only in the worktree** `/Users/picone/LSP-Web-Coordinator/lsp-website/.claude-worktrees/teal-willow` — never edit main-repo paths (worktree-vs-main-path-trap).
- **Member-facing copy uses commas/periods, never em dashes** (em-dash-prose-style memory). All copy in this plan already complies; reproduce it verbatim.
- **DaisyUI semantic tokens only** (`bg-base-100`, `text-base-content`, `btn-primary`, ...) — no hardcoded colors.
- Run tests with `uv run pytest <path> -v`; lint with `uv run ruff check .`.
- `open_to_guests` is **messaging-only**: no registration-time enforcement anywhere.
- Commit after every task; commit messages reference task #464.

---

### Task 1: `Event.open_to_guests` model field + migration

**Files:**
- Modify: `events/models.py` (insert after the `visibility` field, i.e. after line ~423)
- Create: `events/migrations/0038_event_open_to_guests.py` (via `makemigrations`)
- Test: `events/tests.py`

**Interfaces:**
- Produces: `Event.open_to_guests: bool` (default `True`) — used by Tasks 2–4.
- Django admin picks it up automatically (`EventAdminForm.Meta.fields = "__all__"` in `events/admin.py:69-71`); no admin change needed.

- [ ] **Step 1: Write the failing test**

Append to `events/tests.py` (model section, after `test_event_clean_rejects_inverted_dates`):

```python
@pytest.mark.django_db
def test_event_open_to_guests_defaults_true():
    e = Event.objects.create(
        title="Special Evening",
        slug="special-evening",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 1),
    )
    assert e.open_to_guests is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest events/tests.py::test_event_open_to_guests_defaults_true -v`
Expected: FAIL with `AttributeError: 'Event' object has no attribute 'open_to_guests'`

- [ ] **Step 3: Add the field**

In `events/models.py`, directly after the `visibility` field definition (the block ending `help_text=(... "from anonymous visitors on public listings."),)` around line 423), add:

```python
    open_to_guests = models.BooleanField(
        default=True,
        help_text=(
            "Non-members are welcome to register for this event. Shows a "
            "guests-welcome note on the event page. This is messaging only; "
            "it does not restrict who can register."
        ),
    )
```

- [ ] **Step 4: Make the migration**

Run: `uv run python manage.py makemigrations events -n event_open_to_guests`
Expected: creates `events/migrations/0038_event_open_to_guests.py` (AddField, default=True).

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest events/tests.py::test_event_open_to_guests_defaults_true -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add events/models.py events/migrations/0038_event_open_to_guests.py events/tests.py
git commit -m "feat(events): open_to_guests flag on Event (task #464)"
```

---

### Task 2: Expose the flag on the faculty edit form and the PC event form

**Files:**
- Modify: `events/forms.py` — `EventDescriptionForm.Meta.fields` (line ~17-20) and `ProgramEventForm.Meta` (fields line ~398-404, widgets line ~435)
- Modify: `events/templates/events/event_edit.html` (after the `record_video` label block, line ~90-93)
- Modify: `events/templates/events/program_admin/event_form.html` (after the `record_video` div, line ~135-142)
- Test: `events/tests.py`

**Interfaces:**
- Consumes: `Event.open_to_guests` (Task 1).
- Produces: faculty edit form + PC program-admin form both save the flag. The flag is non-reviewable (applies immediately on approved events) because `events/review.py:23` `REVIEWABLE_FIELDS = ("title", "description", "readings", "fee_note")` does not include it — the edit view (`events/views.py:371-382`) applies non-reviewable changed fields immediately.

- [ ] **Step 1: Write the failing tests**

Append to `events/tests.py`:

```python
def test_open_to_guests_is_on_edit_forms_and_not_reviewable():
    from events.forms import EventDescriptionForm, ProgramEventForm
    from events.review import REVIEWABLE_FIELDS

    assert "open_to_guests" in EventDescriptionForm.Meta.fields
    assert "open_to_guests" in ProgramEventForm.Meta.fields
    # Non-reviewable: applies immediately, skips the change-review dialog.
    assert "open_to_guests" not in REVIEWABLE_FIELDS


@pytest.mark.django_db
def test_staff_edit_toggles_open_to_guests_immediately(client):
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
        # record_video / speaker_spotlight / open_to_guests are checkboxes;
        # omitting open_to_guests unchecks it.
    })
    assert resp.status_code == 302
    e.refresh_from_db()
    assert e.open_to_guests is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest events/tests.py::test_open_to_guests_is_on_edit_forms_and_not_reviewable events/tests.py::test_staff_edit_toggles_open_to_guests_immediately -v`
Expected: first FAILS on the `EventDescriptionForm.Meta.fields` assert; second FAILS with `e.open_to_guests is True`.

- [ ] **Step 3: Add the field to both forms**

In `events/forms.py`, `EventDescriptionForm.Meta.fields` becomes:

```python
        fields = (
            "title", "description", "readings", "schedule_note", "contact",
            "fee_note", "record_video", "speaker_spotlight", "open_to_guests",
        )
```

In `ProgramEventForm.Meta.fields`, change the last line of the tuple:

```python
            "requires_faculty_approval", "record_video", "open_to_guests",
```

and add to `ProgramEventForm.Meta.widgets` (next to the `record_video` entry):

```python
            "open_to_guests": forms.CheckboxInput(attrs={"class": "checkbox"}),
```

- [ ] **Step 4: Render the checkbox on both templates**

`events/templates/events/event_edit.html` — after the `speaker_spotlight` label block (ends line ~101), add:

```html
    <label class="flex items-start gap-2 cursor-pointer">
      {{ form.open_to_guests }}
      <span class="label-text">
        Open to guests
        <span class="block text-xs text-base-content/60">Show a note on the event page that non-members are welcome to register. Messaging only, it doesn't restrict who can register.</span>
      </span>
    </label>
```

`events/templates/events/program_admin/event_form.html` — after the `record_video` div (ends line ~142), add:

```html
      <div class="space-y-1">
        <label class="flex items-center gap-2 cursor-pointer">
          {{ form.open_to_guests }}
          <span class="text-sm">Open to guests (shows a non-members-welcome note on the event page)</span>
        </label>
        <p class="text-xs text-base-content/50 pl-7">{{ form.open_to_guests.help_text }}</p>
        {% if form.open_to_guests.errors %}<p class="text-error text-xs pl-7">{{ form.open_to_guests.errors|join:", " }}</p>{% endif %}
      </div>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest events/tests.py::test_open_to_guests_is_on_edit_forms_and_not_reviewable events/tests.py::test_staff_edit_toggles_open_to_guests_immediately -v`
Expected: PASS (both)

- [ ] **Step 6: Run the whole events + registrations suites (regression)**

Run: `uv run pytest events/ registrations/ -q`
Expected: all pass. (If an existing edit-view test posts the old field set, it still passes — an omitted checkbox just unchecks.)

- [ ] **Step 7: Commit**

```bash
git add events/forms.py events/templates/events/event_edit.html events/templates/events/program_admin/event_form.html events/tests.py
git commit -m "feat(events): open_to_guests on faculty + PC edit forms (task #464)"
```

---

### Task 3: Guests-welcome note on the event page (shared partial)

**Files:**
- Modify: `events/templates/events/_event_summary.html` (Registration CTA section, lines 221-234)
- Test: `events/tests.py`

**Interfaces:**
- Consumes: `Event.open_to_guests` (Task 1). The partial already receives `event` and the request context (`user`).
- Produces: the note renders on one-off event detail pages AND seminar/reading-group Workspaces (both include this partial).

- [ ] **Step 1: Write the failing tests**

Append to `events/tests.py`:

```python
def _special_event(**kwargs):
    defaults = dict(
        title="Special Evening", slug="special-evening",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
        status=Event.Status.OPEN, published=True,
    )
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


@pytest.mark.django_db
def test_event_page_shows_guest_note_when_open_to_guests(client):
    e = _special_event()
    resp = client.get(f"/events/{e.slug}/")
    content = resp.content.decode()
    assert "Guests are welcome" in content
    # Anonymous viewers also get the account hint.
    assert "create a free account" in content


@pytest.mark.django_db
def test_event_page_hides_guest_note_when_flag_off(client):
    e = _special_event(open_to_guests=False)
    resp = client.get(f"/events/{e.slug}/")
    assert "Guests are welcome" not in resp.content.decode()


@pytest.mark.django_db
def test_signed_in_viewer_gets_note_without_account_hint(client):
    member = User.objects.create_user(email="m@example.org", password="pw")
    client.force_login(member)
    e = _special_event()
    resp = client.get(f"/events/{e.slug}/")
    content = resp.content.decode()
    assert "Guests are welcome" in content
    assert "create a free account" not in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest events/tests.py -k "guest_note or account_hint" -v`
Expected: FAIL (note not in page); the flag-off test may pass trivially — that's fine, it locks in behavior.

- [ ] **Step 3: Add the note to the partial**

In `events/templates/events/_event_summary.html`, inside the Registration CTA section, immediately after the `{% if user_registration %}...{% endif %}` button block (i.e. after line 228's `{% endif %}`) and before the `{% elif event.status == "draft" %}`, add:

```html
    {% if event.open_to_guests %}
    <p class="text-sm text-base-content/70 mt-2">Open to non-members. Guests are welcome to attend.</p>
    {% if not user.is_authenticated %}
    <p class="text-sm text-base-content/60">You'll be asked to sign in or create a free account. You don't need to be a member.</p>
    {% endif %}
    {% endif %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest events/tests.py -k "guest_note or account_hint" -v`
Expected: PASS (all three)

- [ ] **Step 5: Commit**

```bash
git add events/templates/events/_event_summary.html events/tests.py
git commit -m "feat(events): guests-welcome note by the Register button (task #464)"
```

---

### Task 4: Context-aware login and signup pages

**Files:**
- Modify: `accounts/views.py` (add helper + `LspLoginView`; extend `signup` at line ~131-147)
- Modify: `accounts/urls.py` (line 10: point `login` at the subclass)
- Modify: `accounts/templates/registration/login.html`
- Modify: `accounts/templates/registration/signup.html`
- Test: `accounts/tests.py`

**Interfaces:**
- Consumes: `Event.open_to_guests` not needed here; uses `Event.is_public_now` (existing property, `events/models.py:497`) and URL name `registrations:register` (`registrations/urls.py`).
- Produces: `accounts.views._register_event_from_next(request) -> Event | None`; `accounts.views.LspLoginView` (wired as the `login` URL); both templates receive `register_event` in context.

- [ ] **Step 1: Write the failing tests**

Append to `accounts/tests.py`:

```python
@pytest.mark.django_db
def test_login_page_is_context_aware_for_event_registration(client):
    from datetime import date
    from events.models import Event

    e = Event.objects.create(
        title="Working with Masochism", slug="working-with-masochism",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
        status=Event.Status.OPEN, published=True,
    )
    resp = client.get(f"/accounts/login/?next=/registrations/events/{e.slug}/register/")
    content = resp.content.decode()
    assert "Working with Masochism" in content
    assert "Create a free account" in content


@pytest.mark.django_db
def test_login_page_generic_for_unrelated_or_bad_next(client):
    for nxt in ["/events/", "/registrations/events/no-such-event/register/",
                "https://evil.example/x", ""]:
        resp = client.get("/accounts/login/", {"next": nxt} if nxt else {})
        content = resp.content.decode()
        assert "Sign in to the Lacanian School." in content
        # The promoted signup button shows regardless of context.
        assert "Create a free account" in content


@pytest.mark.django_db
def test_login_page_generic_for_draft_event(client):
    from datetime import date
    from events.models import Event

    e = Event.objects.create(
        title="Hidden Draft", slug="hidden-draft",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
        published=False,
    )
    resp = client.get(f"/accounts/login/?next=/registrations/events/{e.slug}/register/")
    assert "Hidden Draft" not in resp.content.decode()


@pytest.mark.django_db
def test_signup_page_is_context_aware_and_explains_membership(client):
    from datetime import date
    from events.models import Event

    e = Event.objects.create(
        title="Working with Masochism", slug="working-with-masochism",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
        status=Event.Status.OPEN, published=True,
    )
    resp = client.get(f"/accounts/signup/?next=/registrations/events/{e.slug}/register/")
    content = resp.content.decode()
    assert "Working with Masochism" in content
    assert "doesn't make you a member" in content

    # No event context: still shows the explainer, generic heading.
    resp = client.get("/accounts/signup/")
    content = resp.content.decode()
    assert "doesn't make you a member" in content
    assert "Create an account" in content
```

(If `accounts/tests.py` doesn't already import `pytest`, add `import pytest` at the top — check first.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest accounts/tests.py -k "context_aware or generic_for" -v`
Expected: FAIL — no event title, no "Create a free account" button, no "Sign in to the Lacanian School.".

- [ ] **Step 3: Add the helper and LoginView subclass**

In `accounts/views.py`, near `_safe_next` (line ~391), add:

```python
def _register_event_from_next(request):
    """Resolve a safe ``next`` URL to the public event it registers for.

    Returns the Event when ``next`` points at ``registrations:register`` for
    an event that is publicly visible; otherwise None (generic auth copy).
    """
    from django.urls import Resolver404, resolve

    nxt = request.POST.get("next") or request.GET.get("next")
    if not nxt or not nxt.startswith("/") or nxt.startswith("//"):
        return None
    try:
        match = resolve(urlsplit(nxt).path)
    except Resolver404:
        return None
    if match.view_name != "registrations:register":
        return None
    from events.models import Event

    event = Event.objects.filter(slug=match.kwargs.get("slug")).first()
    if event is None or not event.is_public_now:
        return None
    return event


class LspLoginView(auth_views.LoginView):
    """Stock LoginView + guest-friendly context when arriving from a
    Register click (task #464)."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["register_event"] = _register_event_from_next(self.request)
        return context
```

Add the imports at the top of `accounts/views.py` (check which already exist):

```python
from urllib.parse import urlsplit

from django.contrib.auth import views as auth_views
```

In `signup` (line ~143-147), extend the render context:

```python
    return render(
        request,
        "registration/signup.html",
        {
            "form": form,
            "next": request.GET.get("next", ""),
            "register_event": _register_event_from_next(request),
        },
    )
```

In `accounts/urls.py` line 10, replace:

```python
    path("login/", views.LspLoginView.as_view(), name="login"),
```

- [ ] **Step 4: Update the login template**

`accounts/templates/registration/login.html` — replace the header (lines 6-9) with:

```html
  <header class="space-y-1">
    {% if register_event %}
    <h1 class="font-serif text-3xl text-base-content">Sign in</h1>
    <p class="text-sm text-base-content/60">to register for {{ register_event.title }}.</p>
    {% else %}
    <h1 class="font-serif text-3xl text-base-content">Log in</h1>
    <p class="text-sm text-base-content/60">Sign in to the Lacanian School.</p>
    {% endif %}
  </header>
```

and replace the footer "No account?" paragraph (lines 38-41) with a promoted block:

```html
  <div class="divider text-xs text-base-content/40">New to the School?</div>

  <a href="{% url 'signup' %}{% if next %}?next={{ next|urlencode }}{% endif %}" class="btn btn-outline btn-primary w-full">Create a free account</a>
  <p class="text-xs text-base-content/60 text-center">Anyone can create a free account. You don't need to be a member{% if register_event %} to attend{% endif %}.</p>
```

- [ ] **Step 5: Update the signup template**

`accounts/templates/registration/signup.html` — replace the header (lines 6-8) with:

```html
  <header class="space-y-1">
    {% if register_event %}
    <h1 class="font-serif text-3xl text-base-content">Create a free account</h1>
    <p class="text-sm text-base-content/60">to register for {{ register_event.title }}.</p>
    {% else %}
    <h1 class="font-serif text-3xl text-base-content">Create an account</h1>
    {% endif %}
    <p class="text-sm text-base-content/60">An account lets you register for events, pay online, and receive receipts. It doesn't make you a member of the School; membership is by <a href="{% url 'admissions:apply_start' %}" class="link link-primary">application</a>.</p>
  </header>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest accounts/tests.py -k "context_aware or generic_for" -v`
Expected: PASS (all four)

- [ ] **Step 7: Run the accounts suite (regression — magic link, password reset, signup round-trip)**

Run: `uv run pytest accounts/ -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add accounts/views.py accounts/urls.py accounts/templates/registration/login.html accounts/templates/registration/signup.html accounts/tests.py
git commit -m "feat(accounts): context-aware guest-friendly login and signup (task #464)"
```

---

### Task 5: Header Sign-up link for anonymous visitors

**Files:**
- Modify: `core/templates/core/base.html` (line 336-338, the `{% else %}` branch of the auth header)
- Test: `accounts/tests.py`

**Interfaces:**
- Consumes: URL name `signup` (existing).

- [ ] **Step 1: Write the failing test**

Append to `accounts/tests.py`:

```python
@pytest.mark.django_db
def test_header_offers_signup_to_anonymous_visitors(client):
    resp = client.get("/")
    content = resp.content.decode()
    assert 'href="/accounts/signup/"' in content
    assert 'href="/accounts/login/"' in content

    member = User.objects.create_user(email="m2@example.org", password="pw")
    client.force_login(member)
    content = client.get("/").content.decode()
    assert 'href="/accounts/signup/"' not in content
```

(Use the existing `User` import in `accounts/tests.py`; add it if missing: `from accounts.models import User`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest accounts/tests.py::test_header_offers_signup_to_anonymous_visitors -v`
Expected: FAIL — no signup link in the anonymous header.

- [ ] **Step 3: Add the Sign up button**

In `core/templates/core/base.html`, replace line 337:

```html
        <a href="{% url 'login' %}" class="btn btn-ghost btn-sm">Log in</a>
```

with:

```html
        <a href="{% url 'login' %}" class="btn btn-ghost btn-sm">Log in</a>
        <a href="{% url 'signup' %}" class="btn btn-outline btn-primary btn-sm">Sign up</a>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest accounts/tests.py::test_header_offers_signup_to_anonymous_visitors -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/templates/core/base.html accounts/tests.py
git commit -m "feat(core): header Sign up link for anonymous visitors (task #464)"
```

---

### Task 6: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Full test suite**

Run: `uv run pytest -q`
Expected: all pass (CI runs this; a single failure silently aborts deploy — pushed-is-not-deployed).

- [ ] **Step 2: Lint**

Run: `uv run ruff check .`
Expected: clean.

- [ ] **Step 3: Visual smoke check (optional but recommended)**

Run `npm run build:css`, then `uv run python manage.py runserver` and eyeball:
- `/events/<any-open-event>/` — guests-welcome note under the Register button (logged out: extra account hint).
- `/accounts/login/?next=/registrations/events/<slug>/register/` — "Sign in / to register for [title]" + promoted "Create a free account" button.
- `/accounts/signup/` — membership explainer.
- Home page logged out — "Log in" + "Sign up" in the header.

- [ ] **Step 4: Commit any stragglers**

```bash
git status --short
```

Expected: clean (everything committed per task).
