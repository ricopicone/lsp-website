# Registration Admin Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone staff console at `/admin-tools/registrations/` for viewing and acting on registrations across all events, gated to a new (unheld) `registrar` StaffRole + Web Coordinator + serving Programming Committee + Django staff/superusers.

**Architecture:** Follows the referrals-console pattern (module-level `TABS`, `_tab_links()`, `_render()`, app-local `base.html` + `core/_admin_tab_nav.html`) inside the existing `registrations` app, in a new `views_admin.py`. Comp logic is extracted from the Django-admin action into `registrations/services.py` so both surfaces share one side-effect chain. Spec: `docs/superpowers/specs/2026-07-24-registration-admin-design.md`.

**Tech Stack:** Django 5.2, pytest-django, Tailwind v4 + DaisyUI semantic tokens.

## Global Constraints

- DaisyUI semantic tokens only (`bg-base-100`, `text-base-content`, …) — never hardcoded colors.
- Registrar holders must never be publicly badged (join `LSP_STAFF` in the directory-badge exclusion).
- Denied signed-in users get **Http404** (PC-admin convention), anonymous users redirect to login (`@login_required`).
- Every console action writes the dated `staff_notes` audit line convention: `\n[YYYY-MM-DD] <What> by <email> via registration admin.`
- Reuse `Registration.approve()/.decline()`, `payments.notifications` senders, `payments.charges.mint_comped_charge` — no duplicated side-effect chains.
- Run tests with `uv run pytest <file> -x -q`; lint with `uv run ruff check .`.
- Commit after each task.

**Spec amendment (discovered during planning):** `Event.status` DRAFT is "registration not yet open", distinct from the `Event.published` visibility bool. The existing bulk open/close view (`program_admin_registration_bulk`, `events/views.py:698`) flips DRAFT→OPEN on "open". The console's per-event toggle follows that same convention: **open = DRAFT/CLOSED → OPEN; close = OPEN → CLOSED.** Publishing (`published`) stays elsewhere, as the spec intends.

---

### Task 1: `registrar` StaffRole + badge exclusion

**Files:**
- Modify: `core/models.py` (~L74, the well-known keys block)
- Create: `core/migrations/0013_seed_registrar_role.py`
- Modify: `accounts/views.py:88` (badge-exclusion Prefetch)
- Test: `registrations/test_registrar_admin.py` (new file, grows through the plan)

**Interfaces:**
- Produces: `StaffRole.REGISTRAR = "registrar"` constant; a seeded `StaffRole` row with key `registrar`, name "Registrar".

- [ ] **Step 1: Write failing tests**

```python
"""Registration Admin console (/admin-tools/registrations/) — task #470."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import Profile, User
from core.models import StaffRole
from events.models import Audience, Event, PriceTier
from registrations.models import Registration

pytestmark = pytest.mark.django_db


def test_registrar_staff_role_seeded():
    role = StaffRole.objects.get(key=StaffRole.REGISTRAR)
    assert role.name == "Registrar"


def test_registrar_role_never_badges_directory():
    from accounts.views import _badge_staff_roles

    u = User.objects.create_user(email="reg@x.test", password="x")
    StaffRole.objects.get(key=StaffRole.REGISTRAR).holders.add(u)
    # Simulate the _directory_qs prefetch attributes.
    u.public_staff_roles = list(
        StaffRole.objects.filter(holders=u).exclude(
            key__in=(StaffRole.LSP_STAFF, StaffRole.REGISTRAR)
        )
    )
    u.active_public_memberships = []
    assert _badge_staff_roles(u) == []
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest registrations/test_registrar_admin.py -x -q`. Expected: FAIL (`AttributeError: REGISTRAR` / `StaffRole.DoesNotExist`).

- [ ] **Step 3: Implement**

`core/models.py` — after `REFERRAL_COORDINATOR = "referral_coordinator"` add:

```python
    # Registrar — placeholder for a future position (task #470): owns the
    # Registration Admin console. Deliberately never publicly badged.
    REGISTRAR = "registrar"
```

`core/migrations/0013_seed_registrar_role.py`:

```python
"""Seed the Registrar role (task #470).

A placeholder for a position the school hasn't created yet: it gates the
Registration Admin console at /admin-tools/registrations/. Left unheld until
the school appoints someone. Holders are never publicly badged.
"""

from __future__ import annotations

from django.db import migrations

KEY, NAME, DESCRIPTION = (
    "registrar", "Registrar",
    "Manages event registrations across the program: approvals, comps, and "
    "opening/closing registration. Not publicly listed.",
)


def seed(apps, schema_editor):
    StaffRole = apps.get_model("core", "StaffRole")
    StaffRole.objects.get_or_create(
        key=KEY, defaults={"name": NAME, "description": DESCRIPTION},
    )


def unseed(apps, schema_editor):
    apps.get_model("core", "StaffRole").objects.filter(key=KEY).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0012_seed_president_vice_president")]
    operations = [migrations.RunPython(seed, unseed)]
```

`accounts/views.py:86-90` — widen the exclusion (keep the comment accurate):

```python
            # Board-appointed operational roles (Treasurer, Cartel Coordinator,
            # …) badge the directory. LSP Staff and Registrar are internal
            # access designations, not public positions — exclude them.
            # StaffRole.Meta orders by name.
            Prefetch(
                "user__staff_roles",
                queryset=StaffRole.objects.exclude(
                    key__in=(StaffRole.LSP_STAFF, StaffRole.REGISTRAR)
                ),
                to_attr="public_staff_roles",
            ),
```

- [ ] **Step 4: Run tests** — same command. Expected: PASS.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(core): registrar StaffRole, seeded unheld, excluded from directory badges"`

---

### Task 2: Extract comp into `registrations/services.py`

**Files:**
- Create: `registrations/services.py`
- Modify: `registrations/admin.py:32-63` (action body delegates to the service)
- Test: `registrations/test_registrar_admin.py` (append)

**Interfaces:**
- Produces: `registrations.services.comp_registration(reg, by, *, via="admin") -> tuple[bool, bool]` — `(comped, email_ok)`. Only `AWAITING_PAYMENT` rows comp; the side-effect chain is status flip + staff_notes line + `mint_comped_charge` + `registration_confirmed` notification.

- [ ] **Step 1: Write failing tests** (append; also add shared helpers used by later tasks)

```python
def _event(slug="ev", status=Event.Status.OPEN, **kw):
    e = Event.objects.create(
        title=f"Event {slug}", slug=slug, event_type=Event.Type.SEMINAR,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
        published=True, status=status, **kw,
    )
    PriceTier.objects.create(event=e, audience=Audience.ALL, base_amount=Decimal("50.00"))
    return e


def _member(email="m@x.test"):
    u = User.objects.create_user(email=email, password="x", first_name="M", last_name="Ember")
    u.profile.role = Profile.Role.MEMBER
    u.profile.save()
    return u


def _reg(event, user, status=Registration.Status.AWAITING_PAYMENT, amount="50.00"):
    return Registration.objects.create(
        user=user, event=event, price_tier=event.price_tiers.first(),
        quoted_amount=Decimal(amount), status=status,
    )


def test_comp_registration_service_flips_notes_mints_and_notifies():
    from payments.models import Charge
    from registrations.services import comp_registration

    staff = User.objects.create_user(email="s@x.test", password="x", is_staff=True)
    reg = _reg(_event("comp-ev"), _member("c@x.test"))
    comped, email_ok = comp_registration(reg, staff, via="registration admin")

    reg.refresh_from_db()
    assert comped and email_ok
    assert reg.status == Registration.Status.COMPED
    assert "Comped by s@x.test via registration admin." in reg.staff_notes
    assert Charge.objects.filter(registration=reg).exists()


def test_comp_registration_service_refuses_non_awaiting():
    from registrations.services import comp_registration

    staff = User.objects.create_user(email="s2@x.test", password="x", is_staff=True)
    reg = _reg(_event("comp-ev2"), _member("c2@x.test"),
               status=Registration.Status.PAID)
    comped, _ = comp_registration(reg, staff)
    reg.refresh_from_db()
    assert not comped and reg.status == Registration.Status.PAID
```

(If `Charge` has no `registration` field, check `payments/charges.py::mint_comped_charge` for the actual linkage and assert on that — adjust the import/filter accordingly.)

- [ ] **Step 2: Run to verify failure** — Expected: FAIL (`ModuleNotFoundError: registrations.services`).

- [ ] **Step 3: Implement**

`registrations/services.py`:

```python
"""Shared registration staff operations (REG-14).

One home for side-effect chains used by both the Django admin and the
Registration Admin console, so they cannot drift.
"""

from __future__ import annotations

from django.utils import timezone

from payments import notifications as notify_payments

from .models import Registration


def comp_registration(reg, by, *, via: str = "admin") -> tuple[bool, bool]:
    """Comp an awaiting-payment registration (REG-14).

    Flips to COMPED, appends the dated ``staff_notes`` audit line, mints the
    comped ledger charge, and sends the confirmation (with access info).
    Returns ``(comped, email_ok)`` — ``comped`` False when the row wasn't in
    ``AWAITING_PAYMENT``; ``email_ok`` False when the status flip succeeded
    but the notification raised.
    """
    if reg.status != Registration.Status.AWAITING_PAYMENT:
        return False, True
    reg.status = Registration.Status.COMPED
    reg.staff_notes = (reg.staff_notes or "") + (
        f"\n[{timezone.now().date().isoformat()}] Comped by {by.email} via {via}."
    )
    reg.save(update_fields=("status", "staff_notes"))
    from payments.charges import mint_comped_charge
    mint_comped_charge(reg)
    try:
        notify_payments.registration_confirmed(reg)
    except Exception:
        return True, False
    return True, True
```

`registrations/admin.py` — replace the action body's per-reg block with the service (keep the skipped/succeeded/failed message logic):

```python
    @admin.action(description="Comp selected registrations (mark COMPED + email)")
    def comp_selected_registrations(self, request, queryset):
        """Comp registrations not already paid/comped/cancelled/refunded (REG-14)."""
        from .services import comp_registration

        compable = queryset.filter(status=Registration.Status.AWAITING_PAYMENT)
        skipped = queryset.exclude(
            status=Registration.Status.AWAITING_PAYMENT,
        ).count()
        succeeded = 0
        failed = 0
        for reg in compable:
            _, email_ok = comp_registration(reg, request.user, via="admin")
            if not email_ok:
                failed += 1
            succeeded += 1
        msg = f"Comped {succeeded} registration(s)."
        if skipped:
            msg += f" Skipped {skipped} that weren't in 'awaiting payment'."
        if failed:
            msg += f" Email failed for {failed} (status updated regardless)."
        self.message_user(request, msg, level=messages.SUCCESS)
```

Drop the now-unused `timezone` / `notify_payments` imports from `admin.py` if nothing else uses them.

- [ ] **Step 4: Run tests** — new tests + `uv run pytest registrations/ -x -q` (the existing comp-action tests, if any, must stay green). Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "refactor(registrations): extract comp side-effect chain into services.comp_registration"`

---

### Task 3: Gate, console skeleton, Registrations tab, Help tab

**Files:**
- Create: `registrations/permissions.py`
- Create: `registrations/views_admin.py`
- Modify: `registrations/urls.py` (append console routes)
- Create: `registrations/templates/registrations/registrar/base.html`, `registrations.html`, `help.html`
- Create: `core/docs/registrar-guide.md`
- Test: `registrations/test_registrar_admin.py` (append)

**Interfaces:**
- Consumes: `StaffRole.REGISTRAR` (Task 1).
- Produces: `registrations.permissions.can_administer_registrations(user) -> bool`; `registrations.views_admin.registrar_required` decorator; URL names `registrations:registrar`, `registrations:registrar_help`; template `registrations/registrar/base.html` with blocks `tab_content`; view helper `_render(request, tab_key, template, ctx)`.

- [ ] **Step 1: Write failing tests** (append)

```python
from committees.models import Committee


def _registrar(email="registrar@x.test"):
    u = User.objects.create_user(email=email, password="x")
    StaffRole.objects.get(key=StaffRole.REGISTRAR).holders.add(u)
    return u


def _web_coordinator(email="wc@x.test"):
    u = User.objects.create_user(email=email, password="x")
    StaffRole.objects.get(key=StaffRole.WEB_COORDINATOR).holders.add(u)
    return u


def _pc_member(email="pc@x.test"):
    u = User.objects.create_user(email=email, password="x")
    committee, _ = Committee.objects.get_or_create(
        slug="programming-committee",
        defaults={"name": "Programming Committee"},
    )
    committee.add_member(u, start_date=date(2026, 1, 1))
    return u


class TestGate:
    URL = "/admin-tools/registrations/"

    @pytest.mark.parametrize("maker", [_registrar, _web_coordinator, _pc_member])
    def test_admitted_roles(self, client, maker):
        client.force_login(maker())
        assert client.get(self.URL).status_code == 200

    def test_django_staff_admitted(self, client):
        u = User.objects.create_user(email="st@x.test", password="x", is_staff=True)
        client.force_login(u)
        assert client.get(self.URL).status_code == 200

    def test_plain_member_404(self, client):
        client.force_login(_member("plain@x.test"))
        assert client.get(self.URL).status_code == 404

    def test_anonymous_redirects_to_login(self, client):
        resp = client.get(self.URL)
        assert resp.status_code == 302 and "login" in resp.url


def test_registrations_tab_lists_and_filters(client):
    e1, e2 = _event("list-a"), _event("list-b")
    m1, m2 = _member("a@x.test"), _member("b@x.test")
    _reg(e1, m1)
    _reg(e2, m2, status=Registration.Status.PENDING_APPROVAL)
    client.force_login(_registrar("r2@x.test"))

    resp = client.get(reverse("registrations:registrar"))
    body = resp.content.decode()
    assert "a@x.test" in body and "b@x.test" in body
    assert "Needs attention" in body  # pending strip

    resp = client.get(reverse("registrations:registrar"), {"event": e1.pk})
    body = resp.content.decode()
    assert "a@x.test" in body and "b@x.test" not in body

    resp = client.get(reverse("registrations:registrar"),
                      {"status": Registration.Status.PENDING_APPROVAL})
    body = resp.content.decode()
    assert "b@x.test" in body and "a@x.test" not in body

    resp = client.get(reverse("registrations:registrar"), {"q": "a@x.test"})
    body = resp.content.decode()
    assert "a@x.test" in body and "b@x.test" not in body


def test_help_tab_renders(client):
    client.force_login(_registrar("r3@x.test"))
    resp = client.get(reverse("registrations:registrar_help"))
    assert resp.status_code == 200
    assert "Registration Admin" in resp.content.decode()
```

- [ ] **Step 2: Run to verify failure** — Expected: FAIL (404 on URL / `NoReverseMatch`).

- [ ] **Step 3: Implement**

`registrations/permissions.py`:

```python
"""Who may administer registrations (the /admin-tools/registrations/ console).

Task #470: the console belongs to a future Registrar position (StaffRole
minted ahead of the appointment), with the Web Coordinator and the serving
Programming Committee as standing operators. PC access is a live roster
check — no per-member role assignment to manage.
"""

from __future__ import annotations


def can_administer_registrations(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser or user.is_staff:
        return True
    from core.access import has_staff_role
    from core.models import StaffRole
    if has_staff_role(user, StaffRole.REGISTRAR, StaffRole.WEB_COORDINATOR):
        return True
    from events.permissions import is_program_committee
    return is_program_committee(user)
```

`registrations/views_admin.py` (skeleton for this task — actions/CSV/events land in Tasks 4–6):

```python
"""The Registration Admin console (/admin-tools/registrations/) — task #470.

Cross-event registration management for the (future) Registrar, the Web
Coordinator, and the Programming Committee. Follows the referrals-console
tab pattern; the denied-user convention is Http404 (like the PC admin).
"""

from __future__ import annotations

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse

from .models import Registration
from .permissions import can_administer_registrations

PAGE_SIZE = 50


def registrar_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not can_administer_registrations(request.user):
            raise Http404()
        return view(request, *args, **kwargs)
    return wrapper


#: (key, label) for the console's tabs, in display order.
TABS = [
    ("registrations", "Registrations"),
    ("events",        "Events"),
    ("help",          "Help"),
]


def _tab_links() -> list[tuple[str, str, str]]:
    """[(key, label, url), ...] for core/_admin_tab_nav.html."""
    name_to_url = {
        "registrations": reverse("registrations:registrar"),
        "events":        reverse("registrations:registrar_events"),
        "help":          reverse("registrations:registrar_help"),
    }
    return [(key, label, name_to_url[key]) for key, label in TABS]


def _render(request, tab_key: str, template: str, ctx: dict):
    return render(request, template, {
        **ctx, "tab_key": tab_key, "tabs": _tab_links(),
    })


#: Statuses shown under the default "active" filter.
ACTIVE_STATUSES = (
    Registration.Status.PENDING_APPROVAL,
    Registration.Status.AWAITING_PAYMENT,
    Registration.Status.PAID,
    Registration.Status.COMPED,
)


def _filtered_registrations(request):
    """The Registrations-tab queryset for the current GET filters.

    Returns ``(qs, filters)`` where ``filters`` echoes the applied values
    back to the template (and the CSV export reuses both).
    """
    qs = Registration.objects.select_related(
        "user", "user__profile", "event", "price_tier", "pricing_code",
    ).order_by("-created_at")

    status = request.GET.get("status", "active")
    if status == "active":
        qs = qs.filter(status__in=ACTIVE_STATUSES)
    elif status in Registration.Status.values:
        qs = qs.filter(status=status)
    else:
        status = "all"

    event_id = request.GET.get("event") or ""
    if event_id.isdigit():
        qs = qs.filter(event_id=int(event_id))
    else:
        event_id = ""

    since, until = request.GET.get("since") or "", request.GET.get("until") or ""
    if since:
        qs = qs.filter(created_at__date__gte=since)
    if until:
        qs = qs.filter(created_at__date__lte=until)

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(user__email__icontains=q)
            | Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
        )
    return qs, {"status": status, "event": event_id, "since": since,
                "until": until, "q": q}


@registrar_required
def registrar_registrations(request):
    from events.models import Event

    qs, filters = _filtered_registrations(request)
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    pending = (
        Registration.objects.filter(status=Registration.Status.PENDING_APPROVAL)
        .select_related("user", "event")
        .order_by("created_at")
    )
    return _render(request, "registrations",
                   "registrations/registrar/registrations.html", {
        "page": page,
        "pending": pending,
        "filters": filters,
        "status_choices": Registration.Status.choices,
        "event_choices": Event.objects.filter(
            registrations__isnull=False
        ).distinct().order_by("-start_date", "title"),
    })


@registrar_required
def registrar_help(request):
    from core.docs import render_doc
    return _render(request, "help", "registrations/registrar/help.html", {
        "doc_html": render_doc("registrar-guide"),
    })
```

Invalid `since`/`until` values must not 500 — parse with `datetime.date.fromisoformat` before filtering and drop malformed values. Replace the naive since/until block in `_filtered_registrations` with:

```python
    import datetime as _dt

    def _parse_date(raw: str) -> str:
        """Echo back a valid ISO date, or '' for anything malformed."""
        try:
            _dt.date.fromisoformat(raw)
        except ValueError:
            return ""
        return raw

    since = _parse_date(request.GET.get("since") or "")
    until = _parse_date(request.GET.get("until") or "")
    if since:
        qs = qs.filter(created_at__date__gte=since)
    if until:
        qs = qs.filter(created_at__date__lte=until)
```

`registrations/urls.py` — append (module-level `_ADMIN = "admin-tools/registrations"`):

```python
from . import views_admin

_ADMIN = "admin-tools/registrations"

urlpatterns += [
    path(f"{_ADMIN}/", views_admin.registrar_registrations, name="registrar"),
    path(f"{_ADMIN}/help/", views_admin.registrar_help, name="registrar_help"),
]
```

(Define `urlpatterns` additions in the same list literal if preferred; keep `app_name = "registrations"` untouched.)

`registrations/templates/registrations/registrar/base.html` (mirror the referrals base):

```html
{% extends "core/base.html" %}
{% block title %}Registration Admin · LSP{% endblock %}
{% block content %}
<div class="space-y-6">

  <header class="space-y-2">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h1 class="font-serif text-3xl text-base-content">Registration Admin</h1>
      <a href="{% url 'admin_tools' %}" class="btn btn-ghost btn-sm">← Admin Tools</a>
    </div>
  </header>

  {% include "core/_admin_tab_nav.html" %}

  {% if messages %}{% for m in messages %}
  <div class="alert {% if m.tags == 'error' %}alert-error{% elif m.tags == 'warning' %}alert-warning{% else %}alert-success{% endif %} py-2 text-sm">{{ m }}</div>
  {% endfor %}{% endif %}

  <div class="pt-2">
    {% block tab_content %}{% endblock %}
  </div>

</div>
{% endblock %}
```

`registrations/templates/registrations/registrar/registrations.html`:

```html
{% extends "registrations/registrar/base.html" %}
{% block tab_content %}
<div class="space-y-6">

  {% if pending %}
  <section class="rounded-box border border-warning/40 bg-warning/5 p-4 space-y-2">
    <h2 class="font-medium text-base-content">Needs attention
      <span class="badge badge-warning badge-sm align-middle">{{ pending|length }}</span>
    </h2>
    <p class="text-sm text-base-content/70">Registrations awaiting an approval decision.</p>
    <ul class="text-sm space-y-1">
      {% for r in pending %}
      <li class="flex flex-wrap items-center gap-2">
        <span>{{ r.user.get_full_name|default:r.user.email }}</span>
        <span class="text-base-content/60">→ {{ r.event.title }}</span>
        <span class="text-base-content/50">{{ r.created_at|date:"M j" }}</span>
      </li>
      {% endfor %}
    </ul>
  </section>
  {% endif %}

  <form method="get" class="flex flex-wrap items-end gap-2 text-sm">
    <label class="form-control">
      <span class="label-text text-xs">Event</span>
      <select name="event" class="select select-bordered select-sm">
        <option value="">All events</option>
        {% for e in event_choices %}
        <option value="{{ e.pk }}" {% if filters.event == e.pk|stringformat:"s" %}selected{% endif %}>{{ e.title }}</option>
        {% endfor %}
      </select>
    </label>
    <label class="form-control">
      <span class="label-text text-xs">Status</span>
      <select name="status" class="select select-bordered select-sm">
        <option value="active" {% if filters.status == "active" %}selected{% endif %}>Active</option>
        <option value="all" {% if filters.status == "all" %}selected{% endif %}>All</option>
        {% for value, label in status_choices %}
        <option value="{{ value }}" {% if filters.status == value %}selected{% endif %}>{{ label }}</option>
        {% endfor %}
      </select>
    </label>
    <label class="form-control">
      <span class="label-text text-xs">From</span>
      <input type="date" name="since" value="{{ filters.since }}" class="input input-bordered input-sm">
    </label>
    <label class="form-control">
      <span class="label-text text-xs">To</span>
      <input type="date" name="until" value="{{ filters.until }}" class="input input-bordered input-sm">
    </label>
    <label class="form-control grow max-w-xs">
      <span class="label-text text-xs">Search member</span>
      <input type="text" name="q" value="{{ filters.q }}" placeholder="Name or email"
             class="input input-bordered input-sm w-full">
    </label>
    <button class="btn btn-sm btn-primary">Filter</button>
    <a href="{% url 'registrations:registrar' %}" class="btn btn-sm btn-ghost">Reset</a>
  </form>

  <div class="overflow-x-auto">
    <table class="table table-sm">
      <thead>
        <tr>
          <th>Member</th><th>Event</th><th>Tier</th><th class="text-right">Amount</th>
          <th>Status</th><th>Registered</th><th></th>
        </tr>
      </thead>
      <tbody>
        {% for r in page %}
        <tr>
          <td>
            <div>{{ r.user.get_full_name|default:r.user.email }}</div>
            <div class="text-xs text-base-content/60">{{ r.user.email }}</div>
          </td>
          <td><a href="{{ r.event.get_absolute_url }}" class="link link-hover">{{ r.event.title }}</a></td>
          <td class="text-xs">{{ r.price_tier.get_audience_display }}</td>
          <td class="text-right">${{ r.quoted_amount }}</td>
          <td><span class="badge badge-sm
            {% if r.status == 'paid' or r.status == 'comped' %}badge-success
            {% elif r.status == 'pending_approval' %}badge-warning
            {% elif r.status == 'awaiting_payment' %}badge-info
            {% else %}badge-ghost{% endif %}">{{ r.get_status_display }}</span></td>
          <td class="text-xs">{{ r.created_at|date:"M j, Y" }}</td>
          <td><!-- row actions land in Task 4 --></td>
        </tr>
        {% empty %}
        <tr><td colspan="7" class="text-center text-base-content/60 py-6">No registrations match.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  {% if page.paginator.num_pages > 1 %}
  <div class="join">
    {% if page.has_previous %}
    <a class="join-item btn btn-sm" href="?{{ request.GET.urlencode }}&page={{ page.previous_page_number }}">«</a>
    {% endif %}
    <span class="join-item btn btn-sm btn-disabled">Page {{ page.number }} / {{ page.paginator.num_pages }}</span>
    {% if page.has_next %}
    <a class="join-item btn btn-sm" href="?{{ request.GET.urlencode }}&page={{ page.next_page_number }}">»</a>
    {% endif %}
  </div>
  {% endif %}

</div>
{% endblock %}
```

(Note: the naive `?{{ request.GET.urlencode }}&page=` duplicates `page` on repeat paging — strip `page` first in the view by passing a `querystring` context value: `qd = request.GET.copy(); qd.pop("page", None); ctx["querystring"] = qd.urlencode()` and use `?{{ querystring }}&page=…`. Do it that way.)

`registrations/templates/registrations/registrar/help.html`:

```html
{% extends "registrations/registrar/base.html" %}
{% block tab_content %}
<article class="prose prose-sm max-w-3xl">{{ doc_html|safe }}</article>
{% endblock %}
```

`core/docs/registrar-guide.md` — write a real guide (~60 lines) covering: what the console is for and who has access (Registrar / Web Coordinator / Programming Committee / site staff); the Registrations tab (filters, search, CSV export, what each status means, the four row actions and what side-effects each fires — note approve/decline/comp send the member an email); the Events tab (what open/close does, that publishing is separate); what's deliberately elsewhere (offline payments → Treasurer Admin, refunds → member self-service or Treasurer, quoted-amount edits → Django admin per REG-14). Title it `# Registration Admin — a guide`. Follow the `rendered-markdown-docs-gotchas` memory: don't start a wrapped line inside a list item with `+`/`-`/`*`.

- [ ] **Step 4: Run tests** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(registrations): Registration Admin console — gate, Registrations tab, Help (task #470)"`

---

### Task 4: Row actions — approve, decline, comp, add note

**Files:**
- Modify: `registrations/views_admin.py` (four POST views)
- Modify: `registrations/urls.py` (four routes)
- Modify: `registrations/templates/registrations/registrar/registrations.html` (actions cell)
- Test: `registrations/test_registrar_admin.py` (append)

**Interfaces:**
- Consumes: `Registration.approve(by)` / `.decline(by, reason)` (models), `services.comp_registration` (Task 2), `payments.notifications.registration_approved/confirmed/declined`.
- Produces: URL names `registrations:registrar_approve`, `registrar_decline`, `registrar_comp`, `registrar_note` (all POST, per-`reg_id`), each redirecting back to `registrations:registrar` preserving the querystring via a `next` hidden input.

- [ ] **Step 1: Write failing tests** (append)

```python
class TestRowActions:
    def _login_registrar(self, client, email):
        u = _registrar(email)
        client.force_login(u)
        return u

    def test_approve(self, client, django_capture_on_commit_callbacks):
        reg = _reg(_event("act-a"), _member("aa@x.test"),
                   status=Registration.Status.PENDING_APPROVAL)
        u = self._login_registrar(client, "ra@x.test")
        with django_capture_on_commit_callbacks(execute=True):
            resp = client.post(
                reverse("registrations:registrar_approve", args=[reg.id]))
        reg.refresh_from_db()
        assert resp.status_code == 302
        assert reg.status == Registration.Status.AWAITING_PAYMENT
        assert reg.approved_by == u

    def test_decline_with_reason(self, client, django_capture_on_commit_callbacks):
        reg = _reg(_event("act-b"), _member("bb@x.test"),
                   status=Registration.Status.PENDING_APPROVAL)
        self._login_registrar(client, "rb@x.test")
        with django_capture_on_commit_callbacks(execute=True):
            client.post(reverse("registrations:registrar_decline", args=[reg.id]),
                        {"reason": "Full"})
        reg.refresh_from_db()
        assert reg.status == Registration.Status.DECLINED
        assert reg.decline_reason == "Full"

    def test_comp(self, client, django_capture_on_commit_callbacks):
        reg = _reg(_event("act-c"), _member("cc@x.test"))
        self._login_registrar(client, "rc@x.test")
        with django_capture_on_commit_callbacks(execute=True):
            client.post(reverse("registrations:registrar_comp", args=[reg.id]))
        reg.refresh_from_db()
        assert reg.status == Registration.Status.COMPED
        assert "via registration admin." in reg.staff_notes

    def test_comp_wrong_status_refused(self, client):
        reg = _reg(_event("act-d"), _member("dd@x.test"),
                   status=Registration.Status.PAID)
        self._login_registrar(client, "rd@x.test")
        client.post(reverse("registrations:registrar_comp", args=[reg.id]))
        reg.refresh_from_db()
        assert reg.status == Registration.Status.PAID

    def test_note_appends_dated_line(self, client):
        reg = _reg(_event("act-e"), _member("ee@x.test"))
        self._login_registrar(client, "re@x.test")
        client.post(reverse("registrations:registrar_note", args=[reg.id]),
                    {"note": "Spoke by phone; paying by check."})
        reg.refresh_from_db()
        assert "Spoke by phone; paying by check." in reg.staff_notes
        assert "re@x.test" in reg.staff_notes

    def test_actions_gated(self, client):
        reg = _reg(_event("act-f"), _member("ff@x.test"))
        client.force_login(_member("intruder@x.test"))
        resp = client.post(reverse("registrations:registrar_comp", args=[reg.id]))
        assert resp.status_code == 404
        reg.refresh_from_db()
        assert reg.status == Registration.Status.AWAITING_PAYMENT
```

- [ ] **Step 2: Run to verify failure** — Expected: FAIL (`NoReverseMatch`).

- [ ] **Step 3: Implement**

Append to `registrations/views_admin.py`:

```python
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from payments import notifications as notify_payments

from .services import comp_registration


def _back(request):
    """Redirect target preserving the list's filters (posted as ``next``)."""
    nxt = request.POST.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts=None):
        return redirect(nxt)
    return redirect("registrations:registrar")


@registrar_required
@require_POST
def registrar_approve(request, reg_id: int):
    reg = get_object_or_404(Registration, pk=reg_id)
    if reg.approve(request.user):
        if reg.needs_payment:
            notify_payments.registration_approved(reg)
        else:
            notify_payments.registration_confirmed(reg)
        messages.success(request, f"Approved {reg.user.email} for {reg.event.title}.")
    else:
        messages.warning(request, "That registration wasn't pending approval.")
    return _back(request)


@registrar_required
@require_POST
def registrar_decline(request, reg_id: int):
    reg = get_object_or_404(Registration, pk=reg_id)
    if reg.decline(request.user, (request.POST.get("reason") or "").strip()):
        notify_payments.registration_declined(reg)
        messages.success(request, f"Declined {reg.user.email} for {reg.event.title}.")
    else:
        messages.warning(request, "That registration wasn't pending approval.")
    return _back(request)


@registrar_required
@require_POST
def registrar_comp(request, reg_id: int):
    reg = get_object_or_404(Registration, pk=reg_id)
    comped, email_ok = comp_registration(
        reg, request.user, via="registration admin",
    )
    if comped and email_ok:
        messages.success(request, f"Comped {reg.user.email} for {reg.event.title}.")
    elif comped:
        messages.warning(request, "Comped, but the confirmation email failed.")
    else:
        messages.warning(request, "Only awaiting-payment registrations can be comped.")
    return _back(request)


@registrar_required
@require_POST
def registrar_note(request, reg_id: int):
    reg = get_object_or_404(Registration, pk=reg_id)
    note = (request.POST.get("note") or "").strip()
    if note:
        reg.staff_notes = (reg.staff_notes or "") + (
            f"\n[{timezone.now().date().isoformat()}] {note} "
            f"— {request.user.email} via registration admin."
        )
        reg.save(update_fields=("staff_notes",))
        messages.success(request, "Note added.")
    return _back(request)
```

`registrations/urls.py` — append inside the `_ADMIN` block:

```python
    path(f"{_ADMIN}/<int:reg_id>/approve/", views_admin.registrar_approve,
         name="registrar_approve"),
    path(f"{_ADMIN}/<int:reg_id>/decline/", views_admin.registrar_decline,
         name="registrar_decline"),
    path(f"{_ADMIN}/<int:reg_id>/comp/", views_admin.registrar_comp,
         name="registrar_comp"),
    path(f"{_ADMIN}/<int:reg_id>/note/", views_admin.registrar_note,
         name="registrar_note"),
```

Template — replace the empty actions cell with a DaisyUI dropdown (remember the `daisyui-menu-dropdown-overflow` gotcha: `max-height` + `overflow-y-auto` + `flex-nowrap` on `.menu` dropdowns; here the content is small forms, so use a plain `dropdown dropdown-end` with a card body, not `.menu`):

```html
          <td class="text-right">
            <div class="dropdown dropdown-end">
              <button tabindex="0" class="btn btn-ghost btn-xs">Actions ▾</button>
              <div tabindex="0" class="dropdown-content z-20 w-64 rounded-box border border-base-300 bg-base-100 p-3 shadow space-y-3 text-left">
                {% if r.status == 'pending_approval' %}
                <form method="post" action="{% url 'registrations:registrar_approve' r.id %}">
                  {% csrf_token %}
                  <input type="hidden" name="next" value="{{ request.get_full_path }}">
                  <button class="btn btn-success btn-xs w-full">Approve</button>
                </form>
                <form method="post" action="{% url 'registrations:registrar_decline' r.id %}" class="space-y-1">
                  {% csrf_token %}
                  <input type="hidden" name="next" value="{{ request.get_full_path }}">
                  <input type="text" name="reason" placeholder="Reason (optional)"
                         class="input input-bordered input-xs w-full">
                  <button class="btn btn-error btn-xs w-full">Decline</button>
                </form>
                {% endif %}
                {% if r.status == 'awaiting_payment' %}
                <form method="post" action="{% url 'registrations:registrar_comp' r.id %}">
                  {% csrf_token %}
                  <input type="hidden" name="next" value="{{ request.get_full_path }}">
                  <button class="btn btn-outline btn-xs w-full">Comp (no charge)</button>
                </form>
                {% endif %}
                <form method="post" action="{% url 'registrations:registrar_note' r.id %}" class="space-y-1">
                  {% csrf_token %}
                  <input type="hidden" name="next" value="{{ request.get_full_path }}">
                  <input type="text" name="note" placeholder="Add a staff note"
                         class="input input-bordered input-xs w-full">
                  <button class="btn btn-ghost btn-xs w-full">Add note</button>
                </form>
                {% if r.staff_notes %}
                <div class="text-xs text-base-content/60 whitespace-pre-line border-t border-base-300 pt-2">{{ r.staff_notes }}</div>
                {% endif %}
              </div>
            </div>
          </td>
```

Also add the same Approve/Decline forms to each row of the "Needs attention" strip (same markup, `r` bound in that loop).

- [ ] **Step 4: Run tests** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(registrations): console row actions — approve, decline, comp, note"`

---

### Task 5: CSV export

**Files:**
- Modify: `registrations/views_admin.py` (`registrar_registrations_csv`)
- Modify: `registrations/urls.py` (route `registrar_csv`)
- Modify: `registrations/templates/registrations/registrar/registrations.html` (Export button)
- Test: `registrations/test_registrar_admin.py` (append)

**Interfaces:**
- Consumes: `_filtered_registrations(request)` (Task 3).
- Produces: `GET /admin-tools/registrations/export.csv?…` honoring the same filters; columns `event, first_name, last_name, email, role, tier, amount, status, pricing_code, registered_at`.

- [ ] **Step 1: Write failing tests** (append)

```python
def test_csv_export_honors_filters(client):
    e1, e2 = _event("csv-a"), _event("csv-b")
    _reg(e1, _member("csva@x.test"))
    _reg(e2, _member("csvb@x.test"))
    client.force_login(_registrar("rcsv@x.test"))

    resp = client.get(reverse("registrations:registrar_csv"), {"event": e1.pk})
    body = resp.content.decode()
    assert resp["Content-Type"].startswith("text/csv")
    assert "csva@x.test" in body and "csvb@x.test" not in body
    header = body.splitlines()[0]
    assert header == ("event,first_name,last_name,email,role,tier,amount,"
                      "status,pricing_code,registered_at")
```

- [ ] **Step 2: Run to verify failure** — Expected: FAIL (`NoReverseMatch`).

- [ ] **Step 3: Implement** (append to `views_admin.py`; `import csv` and `from django.http import HttpResponse` at top)

```python
@registrar_required
def registrar_registrations_csv(request):
    """CSV of the Registrations tab under the current filters (REG-15 sibling)."""
    qs, _filters = _filtered_registrations(request)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="registrations.csv"'
    writer = csv.writer(response)
    writer.writerow([
        "event", "first_name", "last_name", "email", "role",
        "tier", "amount", "status", "pricing_code", "registered_at",
    ])
    for r in qs:
        writer.writerow([
            r.event.title,
            r.user.first_name,
            r.user.last_name,
            r.user.email,
            getattr(getattr(r.user, "profile", None), "role", ""),
            r.price_tier.get_audience_display(),
            r.quoted_amount,
            r.status,
            r.pricing_code.code if r.pricing_code else "",
            r.created_at.isoformat(),
        ])
    return response
```

URL: `path(f"{_ADMIN}/export.csv", views_admin.registrar_registrations_csv, name="registrar_csv")`.

Template — next to the Filter/Reset buttons:

```html
    <a href="{% url 'registrations:registrar_csv' %}?{{ querystring }}" class="btn btn-sm btn-outline">Export CSV</a>
```

(`querystring` is the page-stripped GET echo added in Task 3.)

Check `PricingCode`'s code field name (`grep -n "code" events/models.py` around the PricingCode model) — if the attribute isn't `.code`, use the actual field.

- [ ] **Step 4: Run tests** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(registrations): console CSV export honoring filters"`

---

### Task 6: Events tab — counts + open/close registration

**Files:**
- Modify: `registrations/views_admin.py` (`registrar_events`, `registrar_event_toggle`)
- Modify: `registrations/urls.py` (routes `registrar_events`, `registrar_event_toggle`)
- Create: `registrations/templates/registrations/registrar/events.html`
- Test: `registrations/test_registrar_admin.py` (append)

**Interfaces:**
- Consumes: `events.models.Event.Status`, `current_academic_year()` + `academic_year_date_range()` from `events.models`.
- Produces: URL names `registrations:registrar_events`, `registrations:registrar_event_toggle` (POST, per-event `pk`, body `action=open|close`).

- [ ] **Step 1: Write failing tests** (append)

```python
class TestEventsTab:
    def test_lists_current_and_upcoming_events_with_counts(self, client):
        e = _event("tab-a")
        _reg(e, _member("ta@x.test"), status=Registration.Status.PAID)
        _reg(e, _member("tb@x.test"))
        client.force_login(_registrar("rev@x.test"))
        resp = client.get(reverse("registrations:registrar_events"))
        body = resp.content.decode()
        assert "Event tab-a" in body
        assert "Close registration" in body  # e is OPEN

    def test_toggle_open_close(self, client):
        e = _event("tab-b", status=Event.Status.DRAFT)
        client.force_login(_registrar("rev2@x.test"))
        client.post(reverse("registrations:registrar_event_toggle", args=[e.pk]),
                    {"action": "open"})
        e.refresh_from_db()
        assert e.status == Event.Status.OPEN

        client.post(reverse("registrations:registrar_event_toggle", args=[e.pk]),
                    {"action": "close"})
        e.refresh_from_db()
        assert e.status == Event.Status.CLOSED

        # Reopen after close.
        client.post(reverse("registrations:registrar_event_toggle", args=[e.pk]),
                    {"action": "open"})
        e.refresh_from_db()
        assert e.status == Event.Status.OPEN

    def test_close_only_applies_to_open(self, client):
        e = _event("tab-c", status=Event.Status.DRAFT)
        client.force_login(_registrar("rev3@x.test"))
        client.post(reverse("registrations:registrar_event_toggle", args=[e.pk]),
                    {"action": "close"})
        e.refresh_from_db()
        assert e.status == Event.Status.DRAFT
```

- [ ] **Step 2: Run to verify failure** — Expected: FAIL (`NoReverseMatch`).

- [ ] **Step 3: Implement** (append to `views_admin.py`)

```python
@registrar_required
def registrar_events(request):
    """One row per current/upcoming-AY event: status + registration counts +
    the open/close toggle. 'Current' = events whose start_date falls on or
    after the start of the current academic year."""
    from django.db.models import Count, Q as _Q

    from events.models import (
        Event, academic_year_date_range, current_academic_year,
    )

    ay_start, _ = academic_year_date_range(current_academic_year())
    events = (
        Event.objects.filter(start_date__gte=ay_start)
        .annotate(
            n_pending=Count("registrations", filter=_Q(
                registrations__status=Registration.Status.PENDING_APPROVAL)),
            n_awaiting=Count("registrations", filter=_Q(
                registrations__status=Registration.Status.AWAITING_PAYMENT)),
            n_paid=Count("registrations", filter=_Q(
                registrations__status=Registration.Status.PAID)),
            n_comped=Count("registrations", filter=_Q(
                registrations__status=Registration.Status.COMPED)),
        )
        .order_by("start_date", "title")
    )
    return _render(request, "events", "registrations/registrar/events.html", {
        "events": events,
    })


@registrar_required
@require_POST
def registrar_event_toggle(request, pk: int):
    """Open or close registration for one event. Mirrors the PC bulk view's
    convention (events/views.py program_admin_registration_bulk): open flips
    DRAFT or CLOSED → OPEN; close flips OPEN → CLOSED. Publishing
    (Event.published) is a separate decision made elsewhere."""
    from events.models import Event

    event = get_object_or_404(Event, pk=pk)
    action = request.POST.get("action")
    if action == "open" and event.status in (
        Event.Status.DRAFT, Event.Status.CLOSED,
    ):
        event.status = Event.Status.OPEN
        event.save(update_fields=("status",))
        messages.success(request, f"Registration opened for {event.title}.")
    elif action == "close" and event.status == Event.Status.OPEN:
        event.status = Event.Status.CLOSED
        event.save(update_fields=("status",))
        messages.success(request, f"Registration closed for {event.title}.")
    else:
        messages.warning(
            request,
            f"No change — {event.title} is "
            f"{event.get_status_display().lower()}.",
        )
    return redirect("registrations:registrar_events")
```

Check the related name on `Registration.event` (`registrations`, per `registrations/models.py` FK `related_name`) — the `Count("registrations", …)` annotations rely on it; verify with `grep -n "related_name" registrations/models.py`.

URLs:

```python
    path(f"{_ADMIN}/events/", views_admin.registrar_events,
         name="registrar_events"),
    path(f"{_ADMIN}/events/<int:pk>/toggle/", views_admin.registrar_event_toggle,
         name="registrar_event_toggle"),
```

`registrations/templates/registrations/registrar/events.html`:

```html
{% extends "registrations/registrar/base.html" %}
{% block tab_content %}
<div class="space-y-4">
  <p class="text-sm text-base-content/70">
    Events in the current and upcoming academic year. Opening registration lets
    members register and pay; it is separate from publishing the event page.
  </p>
  <div class="overflow-x-auto">
    <table class="table table-sm">
      <thead>
        <tr>
          <th>Event</th><th>Starts</th><th>Status</th>
          <th class="text-right">Pending</th><th class="text-right">Awaiting</th>
          <th class="text-right">Paid</th><th class="text-right">Comped</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {% for e in events %}
        <tr>
          <td>
            <a href="{{ e.get_absolute_url }}" class="link link-hover">{{ e.title }}</a>
            {% if not e.published %}<span class="badge badge-warning badge-xs align-middle ml-1">Unpublished</span>{% endif %}
          </td>
          <td class="text-xs">{{ e.start_date|date:"M j, Y" }}</td>
          <td><span class="badge badge-sm {{ e.registration_badge.css }}">{{ e.registration_badge.label }}</span></td>
          <td class="text-right">{{ e.n_pending }}</td>
          <td class="text-right">{{ e.n_awaiting }}</td>
          <td class="text-right">{{ e.n_paid }}</td>
          <td class="text-right">{{ e.n_comped }}</td>
          <td class="text-right">
            <form method="post" action="{% url 'registrations:registrar_event_toggle' e.pk %}">
              {% csrf_token %}
              {% if e.status == 'open' %}
              <input type="hidden" name="action" value="close">
              <button class="btn btn-outline btn-xs">Close registration</button>
              {% else %}
              <input type="hidden" name="action" value="open">
              <button class="btn btn-primary btn-xs">Open registration</button>
              {% endif %}
            </form>
          </td>
        </tr>
        {% empty %}
        <tr><td colspan="8" class="text-center text-base-content/60 py-6">No current or upcoming events.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endblock %}
```

If `Event` has no `get_absolute_url`, link to `{% url 'event_detail' e.slug %}` (check `events/urls.py` for the public event page URL name).

- [ ] **Step 4: Run tests** — Expected: PASS. (Note the test `_event` helper's `start_date=2026-09-01` is in AY 2026-2027 — on today's date (2026-07-24, AY 2025-2026… verify: `academic_year_of` likely splits around Sept 1, so today is AY 2025-2026 and its range starts 2025-09-01; 2026-09-01 ≥ that — included. Good.)
- [ ] **Step 5: Commit** — `git commit -am "feat(registrations): console Events tab — counts + open/close registration"`

---

### Task 7: Hub card, entry gate, STAFF_DOCS

**Files:**
- Modify: `core/staff.py` (PANEL_ROLES, `_can_registrar`, panel card, STAFF_DOCS)
- Test: `registrations/test_registrar_admin.py` (append)

**Interfaces:**
- Consumes: `registrations.permissions.can_administer_registrations`, URL name `registrations:registrar`.

- [ ] **Step 1: Write failing tests** (append)

```python
class TestHub:
    def test_registrar_holder_reaches_hub_and_sees_card(self, client):
        client.force_login(_registrar("hub@x.test"))
        resp = client.get(reverse("admin_tools"))
        assert resp.status_code == 200
        assert "Registration Admin" in resp.content.decode()

    def test_pc_member_sees_card(self, client):
        client.force_login(_pc_member("hubpc@x.test"))
        resp = client.get(reverse("admin_tools"))
        assert "Registration Admin" in resp.content.decode()
```

(Check the hub URL name: `config/urls.py` maps `/admin-tools/` to `core.staff.home` — the name is `admin_tools`, as used in the referrals base template.)

- [ ] **Step 2: Run to verify failure** — Expected: FAIL (registrar holder gets PermissionDenied → 403, and no card).

- [ ] **Step 3: Implement** (`core/staff.py`)

Add `StaffRole.REGISTRAR` to `PANEL_ROLES` (grants hub entry to role holders via the existing `has_staff_role(user, *PANEL_ROLES)` branch in `can_access_admin_tools`; PC members and staff already enter):

```python
PANEL_ROLES = (
    StaffRole.WEB_COORDINATOR,
    StaffRole.TREASURER,
    StaffRole.CARTEL_COORDINATOR,
    StaffRole.ADMIN_ASSISTANT,
    StaffRole.WEB_DEVELOPER,
    StaffRole.REFERRAL_COORDINATOR,
    StaffRole.REGISTRAR,
)
```

Predicate + card in `_panels_for` (place after the Program Committee card so program-adjacent surfaces sit together):

```python
def _can_registrar(user) -> bool:
    from registrations.permissions import can_administer_registrations
    return can_administer_registrations(user)
```

```python
    if _can_registrar(user):
        from registrations.models import Registration
        panels.append({
            "title": "Registration Admin",
            "blurb": "Registrations across all events: approve, comp, and "
                     "open or close registration.",
            "url": reverse("registrations:registrar"),
            "count": Registration.objects.filter(
                status=Registration.Status.PENDING_APPROVAL
            ).count(),
            "count_label": "pending",
        })
```

STAFF_DOCS entry:

```python
    {
        "slug": "registrar-guide",
        "title": "Registration Admin — a guide",
        "blurb": (
            "Managing registrations across all events: approvals, comps, "
            "notes, CSV export, and opening or closing registration."
        ),
    },
```

- [ ] **Step 4: Run tests** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(core): Registration Admin hub card + registrar entry gate + guide doc"`

---

### Task 8: Full verification + docs

**Files:**
- Modify: `CLAUDE.md` (append a "Done" status bullet)

- [ ] **Step 1: Full suite** — `uv run pytest -x -q` (whole repo). Expected: all green. Fix anything the console broke (likely candidates: hub tests asserting exact panel lists, admin tests around the comp action).
- [ ] **Step 2: Lint** — `uv run ruff check .` clean.
- [ ] **Step 3: CLAUDE.md** — add a status bullet under "Done" summarizing the console (placement, gate, tabs, registrar role) in ~6 lines, matching the existing entries' style.
- [ ] **Step 4: Commit** — `git commit -am "docs: CLAUDE.md status entry for the Registration Admin console"`
