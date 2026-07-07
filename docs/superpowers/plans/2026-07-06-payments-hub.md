# Member Payments Hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A login-required member Payments page at `/payments/` that links out to the existing dues/tuition/donate flows and adds the member's own payment history + owner-gated receipt download, reached from the avatar menu.

**Architecture:** Three small additions to the existing `payments` app: an owner-gated receipt view, a member Payments index view + template that composes existing dues/tuition status helpers and lists the member's payments, and an avatar-menu link. No new models; nothing existing is merged or reimplemented.

**Tech Stack:** Django 5.2, Python 3.10, pytest-django, uv, Tailwind v4 + DaisyUI (semantic tokens only).

## Global Constraints

- Django 5.2 / Python 3.10+; deps via `uv` (`uv run …`).
- `accounts.User` is the custom user model; every user has a `Profile`.
- Tests: pytest-django (`uv run pytest`), lint `uv run ruff check .` — keep both green.
- Templates use **DaisyUI semantic tokens only** (`bg-base-100`, `text-base-content`, `text-primary`, …); never hardcoded colors. Tailwind scans templates only.
- **New member-facing copy uses commas, not em dashes** (task #352).
- Do NOT change `/dues/`, `/donate/`, the Tuition tab, checkout, webhook, or receipt-generation logic. This feature composes and links.
- Existing routes/names to link to: `dues` (`/dues/`), `donate` (`/donate/`), `formation:formation` (`/formation/`, tuition at `?tab=tuition`).
- `Payment` fields: `user` (FK, nullable, SET_NULL), `email`, `payment_type` (`Payment.Type`: registration/dues/donation/tuition), `amount`, `currency`, `status` (`Payment.Status`: pending/succeeded/…), and a reverse `receipt` (from `Receipt.payment`). Confirm the timestamp field name (`created_at` vs `paid_at`) by reading `payments/models.py` before ordering on it.
- Frequent commits; each task ends green.

---

### Task 1: Owner-gated member receipt download

**Files:**
- Modify: `payments/views.py` (add `receipt_download`), `payments/urls.py` (add route)
- Test: `payments/test_payments_hub.py` (new)

**Interfaces:**
- Produces: url name `payments:receipt`; view `receipt_download(request, payment_id)` → the member's receipt as a downloadable `text/plain` response; 404 for a non-owner non-staff requester or a payment with no `Receipt`.

- [ ] **Step 1: Write the failing tests**

```python
# payments/test_payments_hub.py
import pytest
from django.urls import reverse
from accounts.models import User
from payments.models import Payment, Receipt


def _paid(user=None, email="", ptype=Payment.Type.DONATION, amount="50.00"):
    p = Payment.objects.create(user=user, email=email, payment_type=ptype,
                               amount=amount, status=Payment.Status.SUCCEEDED)
    Receipt.create_for_payment(p)
    return p


@pytest.mark.django_db
def test_owner_can_download_receipt(client):
    u = User.objects.create_user(email="owner@x.test", password="x")
    p = _paid(user=u)
    client.force_login(u)
    resp = client.get(reverse("payments:receipt", args=[p.pk]), SERVER_NAME="localhost")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/plain")
    assert p.receipt.number.encode() in resp.content


@pytest.mark.django_db
def test_non_owner_gets_404(client):
    owner = User.objects.create_user(email="o@x.test")
    other = User.objects.create_user(email="x@x.test", password="x")
    p = _paid(user=owner)
    client.force_login(other)
    resp = client.get(reverse("payments:receipt", args=[p.pk]), SERVER_NAME="localhost")
    assert resp.status_code == 404
```
Before running, confirm `Receipt` exposes the number attribute (`number`) and `Receipt.create_for_payment` signature by reading `payments/models.py:263-300`; adjust the attribute name in the test if it differs.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest payments/test_payments_hub.py -q`
Expected: FAIL (no url `payments:receipt`).

- [ ] **Step 3: Implement the view**

Read the receipt email render first: `grep -n "email/receipt.txt" payments/*.py` — reuse the exact context dict that call builds so the downloaded receipt matches the emailed one.
```python
# payments/views.py (add near payment_thanks)
from django.http import HttpResponse
from django.template.loader import render_to_string


@login_required
def receipt_download(request, payment_id: int):
    """Serve the member's own receipt as a downloadable text file. 404 unless the
    requester owns the payment (or is staff) and a Receipt exists."""
    payment = get_object_or_404(Payment, pk=payment_id)
    owns = payment.user_id == request.user.id
    if not (owns or request.user.is_staff):
        raise Http404
    receipt = getattr(payment, "receipt", None)
    if receipt is None:
        raise Http404
    # Reuse the canonical receipt content (same template the email uses).
    body = render_to_string("payments/email/receipt.txt", _receipt_context(payment, receipt))
    resp = HttpResponse(body, content_type="text/plain; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{receipt.number}.txt"'
    return resp
```
Replace `_receipt_context(payment, receipt)` with the actual context dict used at the `email/receipt.txt` render site (copy it, or call the existing helper if one exists). Ensure `Http404`, `get_object_or_404`, `login_required` are imported at the top of `payments/views.py`.

- [ ] **Step 4: Wire the URL**

```python
# payments/urls.py — add to urlpatterns
    path("<int:payment_id>/receipt/", views.receipt_download, name="receipt"),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest payments/test_payments_hub.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add payments/views.py payments/urls.py payments/test_payments_hub.py
git commit -m "payments: owner-gated member receipt download"
```

---

### Task 2: Member Payments index page

**Files:**
- Modify: `payments/views.py` (add `payments_index`), `payments/urls.py` (add route)
- Create: `payments/templates/payments/index.html`
- Test: `payments/test_payments_hub.py` (extend)

**Interfaces:**
- Consumes: `payments:receipt` (Task 1); `payments.dues.is_dues_obligated`; `DuesPeriod.amount_for_role`; `Profile.owes_tuition`, `Profile.current_tuition_enrollment()`, `Profile.is_tuition_current()`.
- Produces: url name `payments:index` (`/payments/`); context keys `dues_obligated`, `dues_amount`, `tuition_status`, `payments` (the member's payment list), and a computed `amounts_due` list.

- [ ] **Step 1: Write the failing tests**

```python
# payments/test_payments_hub.py (append)
@pytest.mark.django_db
def test_index_requires_login(client):
    resp = client.get(reverse("payments:index"), SERVER_NAME="localhost")
    assert resp.status_code in (302, 301)


@pytest.mark.django_db
def test_index_lists_only_own_payments(client):
    me = User.objects.create_user(email="me@x.test", password="x")
    other = User.objects.create_user(email="other@x.test")
    mine = _paid(user=me, amount="50.00")
    _paid(user=other, amount="99.00")
    client.force_login(me)
    body = client.get(reverse("payments:index"), SERVER_NAME="localhost").content.decode()
    assert mine.receipt.number in body        # my receipt shown
    assert "$99.00" not in body and "99.00" not in body  # other's payment absent


@pytest.mark.django_db
def test_index_has_dues_tuition_donate_links(client):
    me = User.objects.create_user(email="links@x.test", password="x")
    client.force_login(me)
    body = client.get(reverse("payments:index"), SERVER_NAME="localhost").content.decode()
    assert reverse("dues") in body
    assert reverse("donate") in body
    assert "/formation/?tab=tuition" in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest payments/test_payments_hub.py -q`
Expected: FAIL (no url `payments:index`).

- [ ] **Step 3: Implement the view**

```python
# payments/views.py (add)
from django.db.models import Q
from payments.dues import is_dues_obligated


@login_required
def payments_index(request):
    """The member's central Payments page: what's due, links to dues/tuition/
    donate, and their own payment history with receipts."""
    user = request.user
    profile = user.profile
    payments = (
        Payment.objects.filter(Q(user=user) | Q(email__iexact=user.email))
        .select_related("receipt")
        .order_by("-created_at")   # confirm timestamp field name in models
    )
    ctx = {
        "payments": payments,
        "dues_obligated": is_dues_obligated(user),
        "tuition_enrollment": profile.current_tuition_enrollment(),
        "owes_tuition": profile.owes_tuition,
    }
    return render(request, "payments/index.html", ctx)
```
If `Payment` has no `created_at`, use the real timestamp field (grep `payments/models.py` for `DateTimeField`).

- [ ] **Step 4: Wire the URL**

```python
# payments/urls.py — add (keep it before any catch-all)
    path("", views.payments_index, name="index"),
```

- [ ] **Step 5: Create the template**

`payments/templates/payments/index.html` extends `core/base.html`. Sections (DaisyUI semantic tokens; commas not em dashes):
- Page title "Payments".
- **What's due:** if `dues_obligated`, a row "Dues" with a Pay button linking `{% url 'dues' %}`; if `owes_tuition`, a row "Tuition" with a Pay button linking `/formation/?tab=tuition`. If neither, a calm "You're all paid up." line.
- **Cards** (a responsive grid): "Dues" → `{% url 'dues' %}`; "Tuition" → `/formation/?tab=tuition`; "Donate" → `{% url 'donate' %}`. Each with a one-line description.
- **Payment history:** a `<table>` (wrapped in `overflow-x-auto`) over `payments`: date, `get_payment_type_display`, amount (`${{ p.amount }}`), `get_status_display`; when `p.receipt` exists, a "Download receipt" link to `{% url 'payments:receipt' p.pk %}`. Empty state: "No payments yet."

- [ ] **Step 6: Run tests + live render**

Run:
```bash
uv run pytest payments/test_payments_hub.py -q
uv run python manage.py migrate --run-syncdb -v0
uv run python manage.py shell -c "from django.test import Client; from accounts.models import User; u=User.objects.create_user(email='r@x.test',password='x'); c=Client(); c.force_login(u); print(c.get('/payments/', SERVER_NAME='localhost').status_code)"
```
Expected: tests PASS; page prints 200.

- [ ] **Step 7: Commit**

```bash
git add payments/views.py payments/urls.py payments/templates/payments/index.html payments/test_payments_hub.py
git commit -m "payments: member Payments index page (what's due, links, history)"
```

---

### Task 3: Avatar-menu entry

**Files:**
- Modify: `core/templates/core/base.html` (account/avatar dropdown, near line 277)
- Test: `payments/test_payments_hub.py` (extend)

**Interfaces:**
- Consumes: `payments:index` (Task 2).

- [ ] **Step 1: Write the failing test**

```python
# payments/test_payments_hub.py (append)
@pytest.mark.django_db
def test_avatar_menu_shows_payments(client):
    u = User.objects.create_user(email="menu@x.test", password="x")
    client.force_login(u)
    body = client.get(reverse("payments:index"), SERVER_NAME="localhost").content.decode()
    # The avatar menu renders on every page via base.html.
    assert reverse("payments:index") in body
    assert "Payments" in body
```

- [ ] **Step 2: Run test to verify current state**

Run: `uv run pytest payments/test_payments_hub.py::test_avatar_menu_shows_payments -q`
Expected: it may already pass because the page links to itself; that's fine. The real check is the menu edit renders. Proceed to add the menu item, then re-run.

- [ ] **Step 3: Add the menu item**

In `core/templates/core/base.html`, in the account/avatar dropdown `<ul>` (the one containing `<li><a href="{% url 'donate' %}">Donate to LSP</a></li>` near line 277), add a **Payments** link immediately above the Donate link and group them:
```html
            <li><a href="{% url 'payments:index' %}">Payments</a></li>
            <li><a href="{% url 'donate' %}" class="pl-6">Donate to LSP</a></li>
```
(The `pl-6` visually nests Donate under Payments. Keep the existing Donate `<li>`'s surrounding conditions unchanged; only add the Payments `<li>` and the indent class.)

- [ ] **Step 4: Run the test + a second page to confirm the menu renders site-wide**

Run: `uv run pytest payments/test_payments_hub.py -q`
Expected: PASS. Also render `/` for a logged-in user and confirm "Payments" appears (the menu is global):
```bash
uv run python manage.py shell -c "from django.test import Client; from accounts.models import User; u=User.objects.create_user(email='m2@x.test',password='x'); c=Client(); c.force_login(u); b=c.get('/', SERVER_NAME='localhost').content.decode(); print('Payments' in b and '/payments/' in b)"
```
Expected: `True`.

- [ ] **Step 5: Commit**

```bash
git add core/templates/core/base.html payments/test_payments_hub.py
git commit -m "nav: Payments in the avatar menu, with Donate grouped under it"
```

---

## Self-review (coverage map)

- Central `/payments/` index (spec §1, §The page) → Task 2.
- Links out to dues/tuition/donate, nothing merged (spec §Scope) → Task 2 template + `test_index_has_dues_tuition_donate_links`.
- What's-due summary (spec §The page 1) → Task 2 template.
- Payment history + owner-gated receipts (spec §The page 5, §Backend) → Task 1 (receipt) + Task 2 (history list). Own-only enforced by `test_index_lists_only_own_payments` + `test_non_owner_gets_404`.
- Avatar-menu entry with Donate grouped (spec §Nav wiring) → Task 3.
- Login-required (spec §Permissions) → `test_index_requires_login`.
- Copy commas-not-em-dashes / semantic tokens (global constraints) → Task 2/3 templates.

## Known checks (verify against code, not placeholders)
- The exact `Receipt` number attribute and `create_for_payment` signature (`payments/models.py:263-300`).
- The `email/receipt.txt` render context to reuse (`grep email/receipt.txt payments/*.py`).
- The `Payment` timestamp field name for ordering (`created_at` vs `paid_at`).
- The exact `<ul>` in `base.html` that holds the Donate link (account dropdown, ~line 239-280).
