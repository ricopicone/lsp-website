# Cartel Start-Form Refinements Implementation Plan

> **Execution:** inline (tasks share `forms.py`/`propose.html`/the propose view). Steps use checkbox (`- [ ]`) tracking with TDD.

**Goal:** Refine the cartel start flow: rename "Guiding question" to "Theme" (DB field too), relabel copy ("Start a cartel", "Further description"), add an invitation-only checkbox at start (reusing `closed`), and make invitees a searchable removable-chip picker (reusing `parletre-people-picker.js`).

**Architecture:** `guiding_question` → `theme` via a `RenameField` migration. Invitation-only reuses the existing `closed` flag (checkbox lives only on a `CartelStartForm` subclass so the Settings edit form can't clobber it). Invitees become a `ModelMultipleChoiceField` over directory members, rendered via the existing people-picker component backed by a new `cartels:member_search` endpoint.

**Tech Stack:** Django 5.2, pytest-django, ruff, Tailwind v4 + DaisyUI (templates only), vanilla JS (no Alpine/htmx).

## Global Constraints

- Member-facing copy uses commas, not em dashes. DaisyUI semantic tokens only.
- The `closed` checkbox appears ONLY on the start (propose) form, never on the edit/settings form — else editing details would silently reopen a closed cartel.
- A cartel started `closed=True` is invitation-only: open applications are blocked (`apply` already 404s when `closed`), invitations still work (`accept_invitation` has no closed check), and Settings can reopen (already built).
- `member_search` is login + `is_lsp_member` gated, directory-role-scoped, excludes the requester, returns `{"results": [{"id", "name"}]}` (mirror of `parletre.views.member_search`).
- Keep the cartel suite fully green at each task; run `uv run ruff check cartels/`.

## File Structure

- `cartels/models.py` — `RenameField` target (`theme`), `propose(..., theme="", closed=False)`.
- `cartels/migrations/00XX_rename_theme.py` — `RenameField(guiding_question→theme)`.
- `cartels/forms.py` — rename field to `theme`; `description` label "Further description"; `invitees` → `ModelMultipleChoiceField`; new `CartelStartForm(closed)`.
- `cartels/views.py` — `member_search` view; propose uses `CartelStartForm` (+theme/closed/invitees queryset); edit consumes theme + invitees queryset + passes selected invitees to template.
- `cartels/urls.py` — `member-search/` (before the `<slug:slug>/` patterns).
- `cartels/emails.py`, `cartels/admin.py` — `guiding_question` → `theme`.
- `cartels/templates/cartels/propose.html` — explicit field render + people-picker + closed checkbox + picker script.
- `cartels/templates/cartels/edit.html` — people-picker (preloaded) + theme; picker script.
- `cartels/templates/cartels/_overview.html`, `_settings.html`, `review_queue.html` — "Theme" copy; `_overview.html` + `workgroups/templates/workgroups/_group_card.html` "Invitation only" badge for forming+closed.
- `workgroups/templates/workgroups/kind_list.html` — button "Start a cartel".
- `cartels/tests.py` — rename churn + new tests.

---

### Task 1: Rename `guiding_question` → `theme`

**Files:** `cartels/models.py`, migration, `cartels/forms.py`, `cartels/views.py`, `cartels/emails.py`, `cartels/admin.py`, the three templates, `cartels/tests.py`.

- [ ] **Step 1: Rename the model field**

In `cartels/models.py`, rename the `Cartel.guiding_question` field definition to `theme` (keep `TextField(blank=True)`; update help_text to `"The theme the cartel forms around."`).

- [ ] **Step 2: Generate the RenameField migration**

Run: `uv run python manage.py makemigrations cartels`
Expected: Django prompts "Did you rename cartel.guiding_question to theme (a TextField)? [y/N]" → answer `y` (run with input, or use `--no-input` after confirming it detects the rename; if it creates a remove+add instead, discard and hand-write a `migrations.RenameField(model_name="cartel", old_name="guiding_question", new_name="theme")`).

- [ ] **Step 3: Update all Python references**

`grep -rln "guiding_question" cartels/` and replace `guiding_question` → `theme` in `models.py` (the `propose` kwarg + create call), `views.py` (propose/edit reads), `emails.py` (body text + the "Guiding question:" label → "Theme:"), `admin.py` (`search_fields`), `forms.py` (field name — see Task 3, but rename here for now), and the manager `propose(..., guiding_question="")` param → `theme=""`.

- [ ] **Step 4: Update template copy**

Replace "Guiding question" → "Theme" in `cartels/templates/cartels/_overview.html` (the section heading), `_settings.html` (the inline edit-details label AND the field `name="guiding_question"` → `name="theme"`), and `review_queue.html`. Grep the four cartel templates for `guiding_question`/`Guiding question` and fix all.

- [ ] **Step 5: Update tests**

In `cartels/tests.py`, replace all `guiding_question` (14 occurrences) with `theme` (both kwarg uses in `Cartel.objects.propose(...)` and any attribute assertions / POST data keys).

- [ ] **Step 6: Run tests + lint**

Run: `uv run pytest cartels/ -q` → all pass. `uv run ruff check cartels/` → clean.

- [ ] **Step 7: Commit**

```bash
git add cartels/ && git commit -m "refactor(cartels): rename guiding_question -> theme"
```

---

### Task 2: Copy + invitation-only at start

**Files:** `cartels/forms.py`, `cartels/models.py`, `cartels/views.py`, `cartels/templates/cartels/_overview.html`, `workgroups/templates/workgroups/_group_card.html`, `workgroups/templates/workgroups/kind_list.html`, `cartels/tests.py`.

**Interfaces:**
- Produces: `CartelStartForm(CartelProposalForm)` adding `closed` (BooleanField, required=False); `CartelManager.propose(..., closed=False)` sets `cartel.closed`.

- [ ] **Step 1: Write failing tests**

Add to `cartels/tests.py`:

```python
def test_propose_closed_is_invitation_only():
    gen = _member("g@x.test")
    invitee = _member("inv@x.test")
    cartel = Cartel.objects.propose(
        generator=gen, name="Invite Only", invitees=[invitee], closed=True,
    )
    assert cartel.closed is True
    # open applications blocked
    other = _member("outsider@x.test")
    assert cartel.viewer_state(other)["can_apply"] is False
    # but an invitee can still join
    assert cartel.accept_invitation(invitee) is not None
    assert cartel.is_member(invitee) is True


def test_start_form_checkbox_sets_closed(client):
    gen = _member("g@x.test")
    client.force_login(gen)
    resp = client.post("/cartels/propose/", {"name": "C", "theme": "T", "closed": "on"})
    assert resp.status_code == 302
    cartel = Cartel.objects.get(workgroup__name="C")
    assert cartel.closed is True
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest cartels/tests.py -k "invitation_only or checkbox_sets_closed" -v`
Expected: FAIL — `propose()` has no `closed` kwarg / form ignores it.

- [ ] **Step 3: Add `closed` to `propose()`**

In `cartels/models.py` `CartelManager.propose`, add `closed=False` param and pass it to `self.create(..., closed=closed)`.

- [ ] **Step 4: Add `CartelStartForm`**

In `cartels/forms.py`, after `CartelProposalForm`:

```python
class CartelStartForm(CartelProposalForm):
    """The propose/start form: adds the invitation-only toggle (not on the
    plain edit form, so editing details can't silently reopen a cartel)."""
    closed = forms.BooleanField(
        required=False,
        label="Invitation only, closed to members outside the invited list",
        widget=forms.CheckboxInput(attrs={"class": "checkbox checkbox-sm"}),
    )
```

- [ ] **Step 5: Wire the propose view**

In `cartels/views.py` `propose`, use `CartelStartForm` and pass `closed=form.cleaned_data["closed"]` into `Cartel.objects.propose(...)`. (Import `CartelStartForm`.)

- [ ] **Step 6: Button + badges**

- `workgroups/templates/workgroups/kind_list.html:14` — button text "Propose a cartel" → "Start a cartel".
- `cartels/templates/cartels/_overview.html` badge block — change the `forming and cartel.closed` arm label from "Forming · Closed" to "Invitation only".
- `workgroups/templates/workgroups/_group_card.html` badge block — same change for the forming+closed arm.

- [ ] **Step 7: Run tests + lint**

Run: `uv run pytest cartels/ -q` → all pass. `uv run ruff check cartels/`.

- [ ] **Step 8: Commit**

```bash
git add cartels/ workgroups/ && git commit -m "feat(cartels): invitation-only at start; 'Start a cartel' button"
```

---

### Task 3: Searchable invitees picker + "Further description"

**Files:** `cartels/views.py`, `cartels/urls.py`, `cartels/forms.py`, `cartels/templates/cartels/propose.html`, `cartels/templates/cartels/edit.html`, `cartels/tests.py`.

**Interfaces:**
- Produces: `cartels:member_search` (JSON `{results:[{id,name}]}`); `CartelProposalForm.invitees` = `ModelMultipleChoiceField` over directory members (returns a queryset of Users); `description` label "Further description".

- [ ] **Step 1: Write failing tests**

```python
def test_member_search_returns_directory_members(client):
    me = _member("me@x.test")
    _member("aaa@x.test")  # ensure someone to find
    from accounts.models import User
    target = User.objects.create_user(email="target@x.test", password="x")
    target.first_name = "Zeb"; target.last_name = "Zork"; target.save()
    target.profile.role = Profile.Role.ANALYST; target.profile.save()
    client.force_login(me)
    resp = client.get("/cartels/member-search/", {"q": "Zeb"})
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()["results"]]
    assert target.pk in ids and me.pk not in ids  # excludes self


def test_member_search_requires_login(client):
    resp = client.get("/cartels/member-search/", {"q": "x"})
    assert resp.status_code in (302, 404)


def test_propose_view_invites_by_pk(client):
    gen = _member("g@x.test")
    invitee = _member("inv@x.test")
    client.force_login(gen)
    resp = client.post("/cartels/propose/", {
        "name": "C", "theme": "T", "invitees": [str(invitee.pk)],
    })
    assert resp.status_code == 302
    cartel = Cartel.objects.get(workgroup__name="C")
    assert cartel.invitations.filter(invited_user=invitee).exists()
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest cartels/tests.py -k "member_search or invites_by_pk" -v`
Expected: FAIL — no `member-search/` URL; invitees still comma-text.

- [ ] **Step 3: Add the `member_search` view**

In `cartels/views.py` (imports: `from django.db.models import Q`, `from django.http import JsonResponse`, `from django.contrib.auth import get_user_model`):

```python
@login_required
def member_search(request):
    """Directory-member autocomplete for the invitee picker. Returns id + name."""
    if not is_lsp_member(request.user):
        raise Http404
    q = (request.GET.get("q") or "").strip()
    if not q:
        return JsonResponse({"results": []})
    from accounts.models import Profile
    User = get_user_model()
    qs = User.objects.filter(profile__role__in=Profile.DIRECTORY_ROLES).exclude(pk=request.user.pk)
    for term in q.split()[:3]:
        qs = qs.filter(Q(first_name__icontains=term) | Q(last_name__icontains=term))
    results = [
        {"id": u.pk, "name": u.get_full_name() or u.email}
        for u in qs.order_by("first_name", "last_name")[:8]
    ]
    return JsonResponse({"results": results})
```

- [ ] **Step 4: Add the URL**

In `cartels/urls.py`, add BEFORE the `<slug:slug>/` patterns (next to `propose/`):

```python
    path("member-search/", views.member_search, name="member_search"),
```

- [ ] **Step 5: Convert `invitees` to `ModelMultipleChoiceField` + relabel description**

In `cartels/forms.py`: replace the `invitees` CharField and the `_resolve_member`/`clean_invitees` machinery with a model field. Change `description`'s label to "Further description".

```python
from accounts.models import Profile
from django.contrib.auth import get_user_model

User = get_user_model()


class CartelProposalForm(forms.Form):
    name = forms.CharField(
        max_length=120,
        widget=forms.TextInput(attrs={"class": "input input-bordered w-full"}),
        help_text="A short name for the cartel.",
    )
    theme = forms.CharField(
        widget=forms.Textarea(attrs={
            "rows": 2, "class": "textarea textarea-bordered w-full",
            "placeholder": "The theme the cartel forms around",
        }),
    )
    description = forms.CharField(
        required=False, label="Further description",
        widget=forms.Textarea(attrs={
            "rows": 4, "class": "textarea textarea-bordered w-full",
            "placeholder": "Anything more about this cartel (optional, markdown supported)",
        }),
    )
    invitees = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(), required=False,
        widget=forms.MultipleHiddenInput,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["invitees"].queryset = User.objects.filter(
            profile__role__in=Profile.DIRECTORY_ROLES
        )
```

(`ModelMultipleChoiceField` reads `getlist("invitees")` PKs via `MultipleHiddenInput` and returns a `User` queryset; the picker HTML supplies the hidden inputs.)

- [ ] **Step 6: Update propose + edit views to consume the queryset**

`propose`: `invitees=form.cleaned_data["invitees"]` is already a queryset of Users — `propose()`'s `for user in invitees` loop works unchanged.

`edit`: `for user in form.cleaned_data["invitees"]: cartel.invitations.get_or_create(invited_user=user, defaults={"created_by": request.user})`. On GET, seed the picker's selected chips: pass `selected_invitees = [inv.invited_user for inv in cartel.invitations.filter(accepted_at__isnull=True).select_related("invited_user")]` in the context. On POST re-render (invalid), rebuild `selected_invitees` from `form.data.getlist("invitees")` resolved to Users.

For `propose`, pass `selected_invitees = []` on GET, and on invalid POST rebuild from submitted PKs the same way. Add a small helper in views:

```python
def _selected_invitees(form):
    ids = form.data.getlist("invitees") if form.is_bound else []
    from accounts.models import User
    return list(User.objects.filter(pk__in=ids)) if ids else []
```

- [ ] **Step 7: Render the picker in `propose.html`**

Replace the generic `{% for field in form %}` loop with explicit fields, and add the picker + script. Top of file: `{% extends "core/base.html" %}{% load static %}`. Add before `{% block content %}`:

```html
{% block extra_head %}<script defer src="{% static 'js/parletre-people-picker.js' %}"></script>{% endblock %}
```

Form body (inside the existing `<form method="post">`):

```html
    {% csrf_token %}
    {% if form.non_field_errors %}<div class="alert alert-error text-sm">{{ form.non_field_errors }}</div>{% endif %}

    <div class="space-y-1">
      <label for="{{ form.name.id_for_label }}" class="block text-sm font-medium">Name</label>
      {{ form.name }}
      {% if form.name.errors %}<p class="text-error text-xs">{{ form.name.errors|join:", " }}</p>{% endif %}
    </div>
    <div class="space-y-1">
      <label for="{{ form.theme.id_for_label }}" class="block text-sm font-medium">Theme</label>
      {{ form.theme }}
      {% if form.theme.errors %}<p class="text-error text-xs">{{ form.theme.errors|join:", " }}</p>{% endif %}
    </div>
    <div class="space-y-1">
      <label for="{{ form.description.id_for_label }}" class="block text-sm font-medium">Further description</label>
      {{ form.description }}
      <p class="text-xs text-base-content/60">Optional. Markdown supported.</p>
    </div>
    <div class="space-y-1">
      <label class="block text-sm font-medium">Invite specific members</label>
      <p class="text-xs text-base-content/60">Optional. Search by name to add people to invite directly; you can remove them from the list.</p>
      <div class="people-picker" data-search-url="{% url 'cartels:member_search' %}" data-field="invitees">
        <div class="parletre-people flex flex-wrap gap-2 mb-2" data-people-chips>
          {% for u in selected_invitees %}
          <span class="parletre-chip badge badge-primary gap-1" data-id="{{ u.pk }}">
            {{ u.get_full_name|default:u.email }}
            <button type="button" data-chip-remove aria-label="Remove">&times;</button>
            <input type="hidden" name="invitees" value="{{ u.pk }}">
          </span>
          {% endfor %}
        </div>
        <input type="text" class="input input-bordered w-full" data-people-search
               placeholder="Search members by name" autocomplete="off">
      </div>
      {% if form.invitees.errors %}<p class="text-error text-xs">{{ form.invitees.errors|join:", " }}</p>{% endif %}
    </div>
    <label class="flex items-center gap-2 text-sm">
      {{ form.closed }}
      <span>Invitation only, closed to members outside the invited list</span>
    </label>
```

(Keep the existing Cancel / "Start cartel" button row.)

- [ ] **Step 8: Render the picker in `edit.html`**

Mirror the invitees picker block in `edit.html` (it uses `CartelProposalForm`, no `closed`). Ensure `{% load static %}` + the `extra_head` script block are present, and use `selected_invitees` for preloaded chips. Rename any `guiding_question` field there to `theme` (done in Task 1, verify).

- [ ] **Step 9: Rebuild CSS + run tests + lint**

Run: `npm run build:css` (new classes: `checkbox`, `parletre-chip`, etc. — ensure scanned). Then `uv run pytest cartels/ -q` → all pass. `uv run ruff check cartels/`.

- [ ] **Step 10: Commit**

```bash
git add cartels/ && git commit -m "feat(cartels): searchable invitee picker; 'Further description' label"
```

---

### Task 4: Verify end-to-end + full suite

- [ ] **Step 1: Drive the flow**

Confirm the start form renders the picker, theme, and invitation-only checkbox; a POST with searched invitees + closed creates an invitation-only forming cartel with the seeded invitations. (Covered by tests; spot-check the rendered page via a test client `GET /cartels/propose/` asserting the picker markup + "Start a cartel" is reachable from the kind list.)

- [ ] **Step 2: Full affected suites**

Run: `uv run pytest cartels/ workgroups/ events/ accounts/ -q` → all pass. `uv run ruff check .` → clean.

- [ ] **Step 3: Commit any fixups**

```bash
git add -A && git commit -m "test(cartels): cover start-form refinements" --allow-empty
```

## Self-Review

- Copy: button (Task 2), Further description (Task 3), Theme (Task 1) — ✓.
- Theme DB rename via RenameField (Task 1) — ✓.
- Invitation-only reuses `closed`, checkbox only on start form via `CartelStartForm` (Task 2); Settings reopen untouched — ✓.
- Searchable removable invitees picker reusing `parletre-people-picker.js` + new `member_search` (Task 3); `ModelMultipleChoiceField` validates PKs — ✓.
- Placeholder scan: `00XX` migration name resolved at makemigrations time (Step 1.2) — the only intentional fill-in. No others.
- Consistency: field `theme`, form `invitees` (queryset), `member_search` result shape `{id,name}`, `data-field="invitees"` all aligned across model/form/view/template.
