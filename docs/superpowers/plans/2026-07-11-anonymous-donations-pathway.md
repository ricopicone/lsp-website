# Anonymous Donations Pathway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the "Payments" nav tab to everyone and give logged-out visitors a branching gateway at `/payments/` (sign in to manage payments, or donate anonymously), plus a sign-in nudge on the donate page.

**Architecture:** Two view/template touchpoints and one nav template edit. `payments_index` loses `@login_required` and branches on `request.user.is_authenticated`: authenticated users get the unchanged member page; anonymous users get a new `gateway.html`. The donate flow already supports anonymous gifts (`Payment.user=None`), so no model, migration, or POST-handler changes.

**Tech Stack:** Django 5.2, pytest-django, Tailwind v4 + DaisyUI v5 templates.

## Global Constraints

- DaisyUI semantic tokens only (`bg-base-100`, `text-base-content`, `text-primary`, …) — never hardcoded colors like `bg-gray-100`.
- Member-facing site copy uses commas, not em dashes (`em-dash-prose-style` exception for site copy).
- Deliberate **non-redirect** for anonymous users at `/payments/` — do NOT use `core.access.gate_or_login` (it does the opposite).
- No new models, migrations, or changes to the `donate` POST handler / Stripe session creation.
- Run tests with `uv run pytest`; lint with `uv run ruff check .`. Keep both green.
- URL names available: `login` (accounts), `payments:index`, `donate`.

---

### Task 1: Branch `payments_index` for anonymous visitors

**Files:**
- Modify: `payments/views.py` (`payments_index`, ~line 1303–1322)
- Create: `payments/templates/payments/gateway.html`
- Test: `payments/tests/test_payments_index_public.py` (create)

**Interfaces:**
- Consumes: existing `payments_index` view + `payments/templates/payments/index.html` (member page, unchanged).
- Produces: `/payments/` responds 200 for anonymous users, rendering `payments/gateway.html`; authenticated users still get `payments/index.html`.

- [ ] **Step 1: Write the failing tests**

Create `payments/tests/test_payments_index_public.py`:

```python
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()


@pytest.mark.django_db
def test_payments_index_anonymous_renders_gateway(client):
    resp = client.get(reverse("payments:index"))
    assert resp.status_code == 200
    templates = {t.name for t in resp.templates}
    assert "payments/gateway.html" in templates
    # It must NOT bounce anonymous users to login.
    assert resp.get("Location") is None


@pytest.mark.django_db
def test_payments_gateway_links_to_login_and_donate(client):
    resp = client.get(reverse("payments:index"))
    body = resp.content.decode()
    assert reverse("donate") in body
    assert reverse("login") in body


@pytest.mark.django_db
def test_payments_index_authenticated_renders_member_page(client):
    user = User.objects.create_user(email="member@example.com", password="pw12345!")
    client.force_login(user)
    resp = client.get(reverse("payments:index"))
    assert resp.status_code == 200
    templates = {t.name for t in resp.templates}
    assert "payments/index.html" in templates
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest payments/tests/test_payments_index_public.py -v`
Expected: FAIL — anonymous request currently redirects to login (status 302, `payments/gateway.html` not rendered).

- [ ] **Step 3: Add the anonymous branch to the view**

In `payments/views.py`, remove the `@login_required` decorator on `payments_index` and add an anonymous branch at the top of the function body. Final view:

```python
def payments_index(request):
    """Central Payments page. Authenticated members see what's due, links out to
    dues / tuition / donate, and their own payment history. Anonymous visitors
    see a public gateway: sign in to manage payments, or donate anonymously
    (task #414). Deliberately does NOT redirect anon users to login."""
    if not request.user.is_authenticated:
        return render(request, "payments/gateway.html")

    from payments.dues import is_dues_obligated

    user = request.user
    profile = user.profile
    payments = (
        Payment.objects.filter(Q(user=user) | Q(email__iexact=user.email))
        .select_related("receipt")
        .order_by("-created_at")
    )
    return render(request, "payments/index.html", {
        "payments": payments,
        "dues_obligated": is_dues_obligated(user),
        "owes_tuition": profile.owes_tuition,
        "tuition_enrollment": profile.current_tuition_enrollment(),
    })
```

Also delete the now-unused `@login_required` line directly above the `def payments_index(request):` line. (Leave `@login_required` on the other views untouched.)

- [ ] **Step 4: Create the gateway template**

Create `payments/templates/payments/gateway.html`:

```html
{% extends "core/base.html" %}
{% block title %}Payments · LSP{% endblock %}

{% block page_hero %}{% include "core/_page_hero.html" with title="Payments" %}{% endblock %}

{% block content %}
<div class="max-w-2xl mx-auto space-y-8">

  <p class="text-base-content/70">
    Support the Lacanian School of Psychoanalysis, or sign in to manage your dues,
    tuition, and payment history.
  </p>

  <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
    <a href="{% url 'login' %}?next={% url 'payments:index' %}"
       class="block rounded-lg border border-base-300 bg-base-100 p-5 hover:border-primary transition-colors">
      <div class="font-serif text-lg text-base-content">Sign in to manage your payments</div>
      <p class="text-sm text-base-content/70 mt-1">
        View what's due, pay dues or tuition, and see your receipts and history.
      </p>
      <span class="text-primary text-sm font-medium mt-3 inline-block">Sign in →</span>
    </a>

    <a href="{% url 'donate' %}"
       class="block rounded-lg border border-base-300 bg-base-100 p-5 hover:border-primary transition-colors">
      <div class="font-serif text-lg text-base-content">Donate to LSP</div>
      <p class="text-sm text-base-content/70 mt-1">
        Make a gift to support the School. No account is needed, though signing in
        lets you track your donations.
      </p>
      <span class="text-primary text-sm font-medium mt-3 inline-block">Donate →</span>
    </a>
  </div>

</div>
{% endblock %}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest payments/tests/test_payments_index_public.py -v`
Expected: PASS (all three tests).

- [ ] **Step 6: Lint**

Run: `uv run ruff check payments/views.py`
Expected: no errors (confirm no now-unused imports).

- [ ] **Step 7: Commit**

```bash
git add payments/views.py payments/templates/payments/gateway.html payments/tests/test_payments_index_public.py
git commit -m "feat(payments): public payments gateway for anonymous visitors (task #414)"
```

---

### Task 2: Expose the nav tab + donate sign-in nudge

**Files:**
- Modify: `core/templates/core/base.html` (desktop nav ~line 156–158; mobile menu ~line 206–209)
- Modify: `payments/templates/payments/donate.html` (above the `<form>`)
- Test: `payments/tests/test_payments_index_public.py` (add nudge test)

**Interfaces:**
- Consumes: Task 1's `/payments/` gateway (the nav "Payments" link now targets it for everyone).
- Produces: the "Payments" nav link renders for anonymous users; the donate page shows a sign-in nudge to anonymous users only.

- [ ] **Step 1: Write the failing test**

Add to `payments/tests/test_payments_index_public.py`:

```python
@pytest.mark.django_db
def test_donate_page_shows_signin_nudge_for_anonymous(client):
    resp = client.get(reverse("donate"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "track your donations" in body
    assert reverse("login") in body


@pytest.mark.django_db
def test_donate_page_hides_signin_nudge_for_members(client):
    user = User.objects.create_user(email="m2@example.com", password="pw12345!")
    client.force_login(user)
    resp = client.get(reverse("donate"))
    body = resp.content.decode()
    assert "track your donations" not in body
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest payments/tests/test_payments_index_public.py::test_donate_page_shows_signin_nudge_for_anonymous -v`
Expected: FAIL — nudge copy "track your donations" not present yet.

- [ ] **Step 3: Add the donate-page nudge**

In `payments/templates/payments/donate.html`, insert this block immediately after the opening `<form method="post" class="space-y-4">` line and its `{% csrf_token %}`, before the amount field:

```html
    {% if not user.is_authenticated %}
    <div role="note" class="alert bg-base-200/60 border border-base-300 text-sm">
      <span>
        Have an LSP account?
        <a href="{% url 'login' %}?next={% url 'donate' %}" class="link link-primary">Sign in</a>
        to track your donations and receipts. You can also give anonymously below.
      </span>
    </div>
    {% endif %}
```

- [ ] **Step 4: Expose the nav "Payments" tab for everyone**

In `core/templates/core/base.html`, desktop nav — remove the `{% if user.is_authenticated %}` / `{% endif %}` wrapper around the Payments link so it reads:

```html
          <a href="{% url 'payments:index' %}" class="px-3 py-1.5 rounded-md hover:bg-base-200 {% if '/payments/' in cur or '/dues/' in cur or '/donate/' in cur %}text-primary font-medium{% endif %}">Payments</a>
```

Then in the mobile hamburger menu, change this block:

```html
            {% if user.is_authenticated %}
            <li><hr class="border-base-300/60 my-1"></li>
            <li><a href="{% url 'payments:index' %}">Payments</a></li>
            {% endif %}
```

to (keep the divider, drop the auth guard):

```html
            <li><hr class="border-base-300/60 my-1"></li>
            <li><a href="{% url 'payments:index' %}">Payments</a></li>
```

- [ ] **Step 5: Run the full new test file to verify it passes**

Run: `uv run pytest payments/tests/test_payments_index_public.py -v`
Expected: PASS (all five tests).

- [ ] **Step 6: Rebuild CSS (Tailwind scans templates for new classes) and lint**

Run: `npm run build:css && uv run ruff check .`
Expected: CSS build succeeds; ruff clean. (New template classes — `alert`, `link-primary`, etc. — are already used elsewhere, but rebuild to be safe.)

- [ ] **Step 7: Commit**

```bash
git add core/templates/core/base.html payments/templates/payments/donate.html payments/tests/test_payments_index_public.py
git commit -m "feat(payments): public Payments nav tab + donate sign-in nudge (task #414)"
```

---

## Self-Review

**Spec coverage:**
- Nav tab exposed to everyone → Task 2, Step 4. ✓
- Branching gateway at `/payments/` (sign in / donate) → Task 1. ✓
- Donate page login nudge, still allows anonymous → Task 2, Steps 1–3. ✓
- DaisyUI tokens / commas-not-em-dashes / non-redirect → Global Constraints, honored in templates + view docstring. ✓
- Tests (anon 200 gateway not redirect; auth member page; donate logged-out) → Task 1 Steps 1, Task 2 Step 1. ✓
- No model/migration/POST changes → nothing in the plan touches them. ✓

**Placeholder scan:** none — all code and copy is concrete.

**Type consistency:** template names (`payments/gateway.html`, `payments/index.html`), URL names (`payments:index`, `donate`, `login`), and the test file path are used identically across both tasks. ✓
