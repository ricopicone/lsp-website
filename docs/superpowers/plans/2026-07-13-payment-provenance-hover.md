# Payment Provenance Info Hover — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface each treasurer payment's provenance (`source` + cleaned `notes` + `member_note`) in a hover popover, so the treasurer understands where imported/offline rows came from without opening Django admin.

**Architecture:** A pure template filter cleans the raw `notes` string into readable lines. A reusable popover partial shows a provenance badge + those lines; it renders as a rightmost ⓘ column on tables that lack a source column, and as a hover-on-the-existing-badge on the tuition/dues tabs. A tiny progressive-enhancement script promotes the CSS-hover panel to the native Popover API so it is never clipped by the tables' `overflow-x-auto` wrappers; without JS the CSS `:hover`/`:focus-within` fallback still works.

**Tech Stack:** Django 5.2 templates + template tags, Tailwind v4 + DaisyUI v5 (semantic tokens only), vanilla JS (native Popover API, no dependencies), pytest-django.

## Global Constraints

- **Semantic tokens only** — use DaisyUI tokens (`bg-base-100`, `text-base-content`, `border-base-300`, `text-info`, …). Never hardcoded colors like `bg-gray-100`.
- **Tailwind scans templates only** — every utility class must appear literally in a `.html` file (it does here; no classes set from Python).
- **No new runtime dependencies.** JS is vanilla and self-hosted under `static/js/`.
- **em-dash prose style** in any comments/docs: unspaced em dashes (`word—word`).
- **Tests:** pytest-django; use `@pytest.mark.django_db` only when the DB is needed. The filter and partial-render tests need no DB.
- **This is display-only.** Do not change import commands, the notes format, or add editing from the hover.

---

### Task 1: `provenance_lines` template filter

**Files:**
- Modify: `payments/templatetags/treasurer_filters.py`
- Test: `payments/test_treasurer_filters.py` (create)

**Interfaces:**
- Produces: `provenance_lines(notes: str) -> list[str]` — a registered Django template filter. Splits `notes` on `|`, reformats a leading `[kind:ref]` machine tag into a readable reference line, passes annotations through verbatim, returns `[]` for blank input.

- [ ] **Step 1: Write the failing tests**

Create `payments/test_treasurer_filters.py`:

```python
"""Tests for treasurer template filters (task #435 — provenance hover)."""

import pytest

from payments.templatetags.treasurer_filters import provenance_lines


@pytest.mark.parametrize(
    "notes, expected",
    [
        ("", []),
        ("   ", []),
        (
            "[tz-import:tuition-24-25#1] | installment: 1st | method unrecorded in ledger",
            [
                "Treasurer ledger ref · tuition-24-25#1",
                "installment: 1st",
                "method unrecorded in ledger",
            ],
        ),
        (
            "[tz-import:dues-25-26#17] | method unrecorded in ledger",
            [
                "Treasurer ledger ref · dues-25-26#17",
                "method unrecorded in ledger",
            ],
        ),
        (
            "[stripe-import:ch_3TZxFRKD60xePWRa1QgWKIsY]",
            ["Stripe charge · ch_3TZxFRKD60xePWRa1QgWKIsY"],
        ),
        (
            "[stripe-import:ch_3SwnMBKD60xePWRa1oKdtQxp] (provisional — confirm via dashboard)",
            [
                "Stripe charge · ch_3SwnMBKD60xePWRa1oKdtQxp (provisional — confirm via dashboard)",
            ],
        ),
        (
            "[assume-skip dues-24-25]",
            ["assume-skip dues-24-25"],
        ),
        (
            "Paid by check #4021",
            ["Paid by check #4021"],
        ),
    ],
)
def test_provenance_lines(notes, expected):
    assert provenance_lines(notes) == expected
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest payments/test_treasurer_filters.py -v`
Expected: FAIL — `ImportError: cannot import name 'provenance_lines'`.

- [ ] **Step 3: Implement the filter**

Append to `payments/templatetags/treasurer_filters.py` (the `import re` goes at the top of the file, with the existing imports):

```python
import re

_IMPORT_TAG_LABELS = {
    "tz-import": "Treasurer ledger ref",
    "stripe-import": "Stripe charge",
}

# A leading machine tag like ``[tz-import:tuition-24-25#1]`` optionally followed
# by trailing free text (e.g. a ``(provisional — …)`` parenthetical).
_TAG_RE = re.compile(r"^\[([a-z-]+):([^\]]+)\]\s*(.*)$")
# A bracketed marker without a colon, e.g. ``[assume-skip dues-24-25]``.
_BRACKET_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")


@register.filter
def provenance_lines(notes):
    """Turn a payment/enrollment ``notes`` string into readable display lines.

    Import rows carry a leading machine tag plus ``|``-separated annotations,
    e.g. ``[tz-import:tuition-24-25#1] | installment: 1st | method unrecorded in
    ledger``. The tag becomes a readable reference line; annotations pass
    through verbatim. Returns a list of non-empty strings (``[]`` for blank
    input).
    """
    if not notes or not notes.strip():
        return []
    segments = [s.strip() for s in str(notes).split("|")]
    segments = [s for s in segments if s]
    if not segments:
        return []

    first = segments[0]
    lines = []
    tag = _TAG_RE.match(first)
    if tag:
        kind, ref, trailing = tag.group(1), tag.group(2), tag.group(3).strip()
        label = _IMPORT_TAG_LABELS.get(
            kind,
            kind.replace("-import", "").replace("-", " ").title() + " ref",
        )
        line = f"{label} · {ref}"
        if trailing:
            line = f"{line} {trailing}"
        lines.append(line)
    else:
        bracket = _BRACKET_RE.match(first)
        if bracket:
            lines.append(f"{bracket.group(1).strip()} {bracket.group(2).strip()}".strip())
        else:
            lines.append(first)

    lines.extend(segments[1:])
    return lines
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest payments/test_treasurer_filters.py -v`
Expected: PASS (8 parametrized cases).

- [ ] **Step 5: Lint**

Run: `uv run ruff check payments/templatetags/treasurer_filters.py payments/test_treasurer_filters.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add payments/templatetags/treasurer_filters.py payments/test_treasurer_filters.py
git commit -m "feat(treasurer): provenance_lines filter to clean payment notes (task #435)"
```

---

### Task 2: Provenance popover partials + progressive-enhancement script

**Files:**
- Create: `payments/templates/payments/treasurer/_provenance_body.html`
- Create: `payments/templates/payments/treasurer/_provenance_popover.html`
- Create: `static/js/provenance-hover.js`
- Modify: `payments/templates/payments/treasurer/base.html`
- Test: `payments/test_treasurer_filters.py` (add render tests)

**Interfaces:**
- Consumes: `provenance_lines` (Task 1), existing `payments/treasurer/_source_badge.html` (params `source`, `label`).
- Produces: partial `payments/treasurer/_provenance_popover.html`, included with params:
  `source` (key), `source_label` (display), `notes` (str, optional), `member_note` (str, optional), `trigger` (`"icon"` default, or `"badge"`).
  - `trigger="icon"`: renders **nothing** unless `notes or member_note`; otherwise a ⓘ button + popover (popover body includes the source badge).
  - `trigger="badge"`: **always** renders the source badge; wraps it in a hover popover only when `notes or member_note`.
  - Trigger element carries `data-prov-trigger`; the panel (its next sibling) carries `data-prov-panel`.

- [ ] **Step 1: Write the failing render tests**

Add to `payments/test_treasurer_filters.py`:

```python
from django.template.loader import render_to_string


def _render(**ctx):
    base = {"source": "staff", "source_label": "Entered by staff",
            "notes": "", "member_note": "", "trigger": "icon"}
    base.update(ctx)
    return render_to_string("payments/treasurer/_provenance_popover.html", base)


def test_popover_icon_shows_source_and_cleaned_notes():
    html = _render(
        source="imported", source_label="Imported from treasurer ledger",
        notes="[tz-import:tuition-24-25#1] | method unrecorded in ledger",
        trigger="icon",
    )
    assert "Imported from treasurer ledger" in html
    assert "Treasurer ledger ref · tuition-24-25#1" in html
    assert "method unrecorded in ledger" in html
    assert "data-prov-trigger" in html
    assert "data-prov-panel" in html


def test_popover_icon_empty_when_no_notes():
    html = _render(trigger="icon")
    assert html.strip() == ""


def test_popover_badge_always_shows_but_no_hover_without_notes():
    html = _render(source_label="Entered by staff", trigger="badge")
    assert "Entered by staff" in html
    assert "data-prov-trigger" not in html


def test_popover_badge_gets_hover_with_notes():
    html = _render(
        source="imported", source_label="Imported from treasurer ledger",
        notes="[tz-import:dues-25-26#17] | method unrecorded in ledger",
        trigger="badge",
    )
    assert "Imported from treasurer ledger" in html
    assert "data-prov-trigger" in html
    assert "Treasurer ledger ref · dues-25-26#17" in html


def test_popover_shows_member_note():
    html = _render(notes="", member_note="Paid at the door, will confirm.", trigger="icon")
    assert "Paid at the door, will confirm." in html
    assert "data-prov-trigger" in html
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest payments/test_treasurer_filters.py -k popover -v`
Expected: FAIL — `TemplateDoesNotExist: payments/treasurer/_provenance_popover.html`.

- [ ] **Step 3: Create the body partial**

Create `payments/templates/payments/treasurer/_provenance_body.html`:

```django
{% comment %}
Popover body: cleaned notes lines + optional member note.
Params: notes (str), member_note (str, optional).
{% endcomment %}
{% load treasurer_filters %}
{% for line in notes|provenance_lines %}
<div class="text-xs text-base-content/70 leading-snug">{{ line }}</div>
{% endfor %}
{% if member_note %}
<div class="text-xs text-info/80 italic leading-snug pt-1">Member note: “{{ member_note }}”</div>
{% endif %}
```

- [ ] **Step 4: Create the popover partial**

Create `payments/templates/payments/treasurer/_provenance_popover.html`:

```django
{% comment %}
Provenance hover popover. Params:
  source        — provenance key (Payment/enrollment .source)
  source_label  — display label (get_source_display / source_label)
  notes         — raw notes string (optional)
  member_note   — member's note (optional)
  trigger       — "icon" (default) or "badge"

trigger="icon": renders nothing unless there is notes/member_note.
trigger="badge": always renders the source badge; adds the hover only when
there is notes/member_note.

The panel carries CSS :hover / :focus-within fallback classes AND
data-prov-panel; provenance-hover.js promotes it to the native Popover API so
it escapes the tables' overflow-x-auto clipping.
{% endcomment %}
{% if trigger == "badge" %}
  {% if notes or member_note %}
  <span class="group relative inline-flex items-center">
    <span data-prov-trigger tabindex="0" role="button" aria-label="Payment source and notes" class="cursor-help">
      {% include "payments/treasurer/_source_badge.html" with source=source label=source_label %}
    </span>
    <span data-prov-panel class="hidden group-hover:block group-focus-within:block absolute z-20 left-0 top-full mt-1 w-64 rounded-lg border border-base-300 bg-base-100 p-3 text-left shadow-lg space-y-1.5">
      {% include "payments/treasurer/_provenance_body.html" with notes=notes member_note=member_note %}
    </span>
  </span>
  {% else %}
  {% include "payments/treasurer/_source_badge.html" with source=source label=source_label %}
  {% endif %}
{% else %}
  {% if notes or member_note %}
  <span class="group relative inline-flex items-center justify-end">
    <span data-prov-trigger tabindex="0" role="button" aria-label="Payment source and notes" class="cursor-help text-base-content/40 hover:text-base-content/70">
      <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <circle cx="12" cy="12" r="9" /><line x1="12" y1="16" x2="12" y2="11" /><line x1="12" y1="8" x2="12" y2="8" stroke-linecap="round" />
      </svg>
    </span>
    <span data-prov-panel class="hidden group-hover:block group-focus-within:block absolute z-20 right-0 top-full mt-1 w-64 rounded-lg border border-base-300 bg-base-100 p-3 text-left shadow-lg space-y-1.5">
      <div>{% include "payments/treasurer/_source_badge.html" with source=source label=source_label %}</div>
      {% include "payments/treasurer/_provenance_body.html" with notes=notes member_note=member_note %}
    </span>
  </span>
  {% endif %}
{% endif %}
```

- [ ] **Step 5: Run render tests to verify they pass**

Run: `uv run pytest payments/test_treasurer_filters.py -k popover -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Create the progressive-enhancement script**

Create `static/js/provenance-hover.js`:

```javascript
/* Treasurer payment provenance popovers (task #435).
   Promotes the CSS-hover panels to the native Popover API so they render in
   the top layer and are never clipped by the tables' overflow-x-auto wrappers.
   Without the Popover API the markup's :hover / :focus-within fallback works. */
(function () {
  "use strict";
  if (!("popover" in HTMLElement.prototype)) return;

  document.querySelectorAll("[data-prov-trigger]").forEach(function (trigger) {
    var panel = trigger.nextElementSibling;
    if (!panel || !panel.hasAttribute("data-prov-panel")) return;

    // Take over from the CSS fallback so the panel does not show twice.
    panel.classList.remove("group-hover:block", "group-focus-within:block");
    panel.setAttribute("popover", "manual");

    var hideTimer = null;
    function cancelHide() {
      if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
    }
    function scheduleHide() {
      cancelHide();
      hideTimer = setTimeout(function () { panel.hidePopover(); }, 120);
    }
    function show() {
      cancelHide();
      panel.style.position = "fixed";
      panel.style.margin = "0";
      panel.style.left = "-9999px";
      panel.style.top = "-9999px";
      panel.showPopover();
      var t = trigger.getBoundingClientRect();
      var p = panel.getBoundingClientRect();
      var left = Math.max(8, Math.min(t.right - p.width, window.innerWidth - p.width - 8));
      var top = t.bottom + 6;
      if (top + p.height > window.innerHeight - 8) {
        top = Math.max(8, t.top - p.height - 6);
      }
      panel.style.left = left + "px";
      panel.style.top = top + "px";
    }

    trigger.addEventListener("pointerenter", show);
    trigger.addEventListener("focus", show);
    trigger.addEventListener("pointerleave", scheduleHide);
    trigger.addEventListener("blur", scheduleHide);
    panel.addEventListener("pointerenter", cancelHide);
    panel.addEventListener("pointerleave", scheduleHide);
  });
})();
```

- [ ] **Step 7: Load the script on treasurer pages**

In `payments/templates/payments/treasurer/base.html`, add the script inside the existing `{% block extra_head %}`, after the chart scripts and before `{% block tab_head %}`:

```django
<script src="{% static 'js/provenance-hover.js' %}" defer></script>
```

- [ ] **Step 8: Run the full filter test file + lint**

Run: `uv run pytest payments/test_treasurer_filters.py -v && uv run ruff check payments/`
Expected: PASS, no lint errors.

- [ ] **Step 9: Commit**

```bash
git add payments/templates/payments/treasurer/_provenance_body.html payments/templates/payments/treasurer/_provenance_popover.html static/js/provenance-hover.js payments/templates/payments/treasurer/base.html payments/test_treasurer_filters.py
git commit -m "feat(treasurer): provenance hover popover partial + script (task #435)"
```

---

### Task 3: Wire the ⓘ column into member-detail + Payments tab

**Files:**
- Modify: `payments/templates/payments/treasurer/member_detail.html:66-86`
- Modify: `payments/templates/payments/treasurer/payments.html:48-116`
- Test: `payments/test_provenance_hover_views.py` (create)

**Interfaces:**
- Consumes: `_provenance_popover.html` (Task 2), `treasurer_member_detail` view (existing, gated by `_is_staff`), `treasurer_payments` view (existing).

- [ ] **Step 1: Write the failing view test**

Create `payments/test_provenance_hover_views.py`:

```python
"""The provenance hover appears on the treasurer member-detail page (task #435)."""

import pytest
from django.urls import reverse

from accounts.models import User
from core.models import StaffRole
from payments.models import Payment


@pytest.mark.django_db
def test_member_detail_shows_provenance_hover(client):
    treasurer = User.objects.create_user(email="treas@x.test", password="x")
    StaffRole.objects.create(user=treasurer, role=StaffRole.Role.TREASURER)
    member = User.objects.create_user(email="member@x.test", password="x")
    Payment.objects.create(
        user=member, payment_type=Payment.Type.TUITION, amount="500.00",
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        source="imported",
        notes="[tz-import:tuition-24-25#1] | method unrecorded in ledger",
    )
    client.force_login(treasurer)
    resp = client.get(
        reverse("treasurer_member_detail", args=[member.id]),
        SERVER_NAME="localhost",
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "data-prov-trigger" in body
    assert "Treasurer ledger ref · tuition-24-25#1" in body
    assert "method unrecorded in ledger" in body
```

Note: confirm the treasurer-role grant matches this codebase. Before writing, check how existing treasurer tests authorize a user — search: `grep -rn "TREASURER\|StaffRole\|_is_staff" payments/test_*.py core/staff.py`. Use the same mechanism those tests use; adjust the `StaffRole.objects.create(...)` line to match (the role enum member name may differ).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest payments/test_provenance_hover_views.py -v`
Expected: FAIL — `data-prov-trigger` not in body (column not wired yet). (If it fails on auth/403 instead, fix the role grant per the Step 1 note first.)

- [ ] **Step 3: Wire member_detail.html**

In `payments/templates/payments/treasurer/member_detail.html`, change the Payments table header row (line 68) from:

```django
          <tr><th>Date</th><th>Type</th><th>Amount</th><th>Method</th><th>Status</th></tr>
```

to:

```django
          <tr><th>Date</th><th>Type</th><th>Amount</th><th>Method</th><th>Status</th><th class="w-8"></th></tr>
```

Then add a trailing cell inside the row, immediately after the Status `<td>` (currently line 82 `<td>{% status_badge p.status %}</td>`):

```django
            <td class="text-right">
              {% include "payments/treasurer/_provenance_popover.html" with source=p.source source_label=p.get_source_display notes=p.notes member_note=p.member_note trigger="icon" %}
            </td>
```

- [ ] **Step 4: Run the member-detail test to verify it passes**

Run: `uv run pytest payments/test_provenance_hover_views.py -v`
Expected: PASS.

- [ ] **Step 5: Wire payments.html (Payments tab)**

In `payments/templates/payments/treasurer/payments.html`:

(a) Add an Info header as the **last** column. Change the `<th>Actions</th>` line (line 56) block so the header row ends:

```django
          <th>Status</th>
          <th>Actions</th>
          <th class="w-8"></th>
```

(b) Add a trailing cell as the last cell of the data row, immediately after the Actions `</td>` (after line 116):

```django
          <td class="text-right">
            {% include "payments/treasurer/_provenance_popover.html" with source=p.source source_label=p.get_source_display notes=p.notes member_note=p.member_note trigger="icon" %}
          </td>
```

(c) Remove the now-duplicate member-note line from the Type cell (lines 80-82):

```django
            {% if p.member_note %}
            <div class="text-xs text-info/80 italic" title="Member note">“{{ p.member_note|truncatechars:60 }}”</div>
            {% endif %}
```

(d) Update the empty-state `colspan` (line 120) from `colspan="7"` to `colspan="8"`.

- [ ] **Step 6: Add a Payments-tab assertion**

Add to `payments/test_provenance_hover_views.py`:

```python
@pytest.mark.django_db
def test_payments_tab_shows_provenance_hover(client):
    treasurer = User.objects.create_user(email="treas2@x.test", password="x")
    StaffRole.objects.create(user=treasurer, role=StaffRole.Role.TREASURER)
    member = User.objects.create_user(email="m2@x.test", password="x")
    Payment.objects.create(
        user=member, payment_type=Payment.Type.TUITION, amount="500.00",
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        source="imported",
        notes="[tz-import:tuition-24-25#1] | method unrecorded in ledger",
    )
    client.force_login(treasurer)
    resp = client.get(reverse("treasurer_payments"), SERVER_NAME="localhost")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "data-prov-trigger" in body
    assert "Treasurer ledger ref · tuition-24-25#1" in body
```

Confirm the URL name with `grep -n "treasurer_payments" payments/urls.py`; adjust if different.

- [ ] **Step 7: Run both view tests + lint**

Run: `uv run pytest payments/test_provenance_hover_views.py -v && uv run ruff check payments/`
Expected: PASS, no lint errors.

- [ ] **Step 8: Commit**

```bash
git add payments/templates/payments/treasurer/member_detail.html payments/templates/payments/treasurer/payments.html payments/test_provenance_hover_views.py
git commit -m "feat(treasurer): provenance ⓘ column on member-detail + Payments tab (task #435)"
```

---

### Task 4: Wire badge-hover into tuition + dues tabs

**Files:**
- Modify: `payments/views.py:892-897` (add `notes` to tuition enrollment rows)
- Modify: `payments/templates/payments/treasurer/tuition.html:155`
- Modify: `payments/templates/payments/treasurer/dues.html:133`
- Test: `payments/test_provenance_hover_views.py` (add dues assertion)

**Interfaces:**
- Consumes: `_provenance_popover.html` with `trigger="badge"`. dues rows are `Payment` objects (`p.source`, `p.get_source_display`, `p.notes`, `p.member_note`); tuition rows are dicts needing a new `notes` key from `TuitionEnrollment.notes`.

- [ ] **Step 1: Add `notes` to the tuition enrollment rows**

In `payments/views.py`, in the `enrollment_rows.append({...})` dict (currently lines 892-897), add a `notes` key:

```python
        enrollment_rows.append({
            "user": e.user, "status": e.status,
            "status_label": status_labels.get(e.status, e.status),
            "source": e.source, "source_label": e.get_source_display(),
            "notes": e.notes,
            "paid": paid, "remaining": remaining,
        })
```

- [ ] **Step 2: Wire dues.html**

In `payments/templates/payments/treasurer/dues.html`, replace the source cell (line 133):

```django
            <td>{% include "payments/treasurer/_source_badge.html" with source=p.source label=p.get_source_display %}</td>
```

with:

```django
            <td>{% include "payments/treasurer/_provenance_popover.html" with source=p.source source_label=p.get_source_display notes=p.notes member_note=p.member_note trigger="badge" %}</td>
```

- [ ] **Step 3: Wire tuition.html**

In `payments/templates/payments/treasurer/tuition.html`, replace the source cell (line 155):

```django
            <td>{% include "payments/treasurer/_source_badge.html" with source=row.source label=row.source_label %}</td>
```

with:

```django
            <td>{% include "payments/treasurer/_provenance_popover.html" with source=row.source source_label=row.source_label notes=row.notes trigger="badge" %}</td>
```

- [ ] **Step 4: Add a dues-tab test**

Add to `payments/test_provenance_hover_views.py`:

```python
from payments.models import DuesPeriod


@pytest.mark.django_db
def test_dues_tab_badge_gets_hover(client):
    treasurer = User.objects.create_user(email="treas3@x.test", password="x")
    StaffRole.objects.create(user=treasurer, role=StaffRole.Role.TREASURER)
    member = User.objects.create_user(email="m3@x.test", password="x")
    period = DuesPeriod.objects.create(
        name="2025–26", start_date="2025-09-01", end_date="2026-08-31",
        is_current=True,
    )
    Payment.objects.create(
        user=member, payment_type=Payment.Type.DUES, amount="100.00",
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        dues_period=period, source="imported",
        notes="[tz-import:dues-25-26#17] | method unrecorded in ledger",
    )
    client.force_login(treasurer)
    resp = client.get(reverse("treasurer_dues"), SERVER_NAME="localhost")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "data-prov-trigger" in body
    assert "Treasurer ledger ref · dues-25-26#17" in body
```

Confirm the `DuesPeriod` constructor fields and the `treasurer_dues` URL name against the codebase first (`grep -n "class DuesPeriod" payments/models.py`, `grep -n "treasurer_dues" payments/urls.py`); adjust the `create(...)` kwargs and any required period fields (e.g. role-tier amounts) to satisfy validation.

- [ ] **Step 5: Run the dues test to verify it passes**

Run: `uv run pytest payments/test_provenance_hover_views.py::test_dues_tab_badge_gets_hover -v`
Expected: PASS.

- [ ] **Step 6: Run the full payments test suite + lint**

Run: `uv run pytest payments/ -q && uv run ruff check payments/`
Expected: PASS, no lint errors. (Confirms no regression from the tuition-row dict change and the payments.html colspan.)

- [ ] **Step 7: Commit**

```bash
git add payments/views.py payments/templates/payments/treasurer/tuition.html payments/templates/payments/treasurer/dues.html payments/test_provenance_hover_views.py
git commit -m "feat(treasurer): provenance hover on tuition + dues source badges (task #435)"
```

---

### Task 5: Build assets + manual browser verification

**Files:** none (verification only).

- [ ] **Step 1: Rebuild CSS so the new utility classes are present**

Run: `npm run build:css`
Expected: `static/css/site.css` rebuilds without error. (Tailwind must scan the new partials so classes like `group-hover:block`, `cursor-help`, `w-64` are emitted.)

- [ ] **Step 2: Run the dev server and drive the flow**

Use the `verify` skill (or `run` skill) to launch the app, sign in as a treasurer, and open the treasurer Payments tab and a member-detail page for a member with imported payments (locally, seed one via the shell if needed). Confirm:
  - The ⓘ icon appears only on rows with notes; hovering shows the source badge + cleaned lines (e.g. "Treasurer ledger ref · …", "method unrecorded in ledger").
  - On the tuition/dues tabs, hovering the source badge reveals the notes; badges without notes show no popover.
  - The popover is not clipped by the table's horizontal-scroll wrapper on the bottom rows (Popover API top-layer working).
  - Keyboard: Tab to the trigger shows the popover on focus.

- [ ] **Step 3: Full test suite**

Run: `uv run pytest -q`
Expected: PASS (whole suite green — this is what CI/deploy gates on; see the `pushed-is-not-deployed` note).

---

## Notes for the implementer

- **Do not** hand-edit `static/css/site.css` — it is generated and `.gitignore`'d.
- The JS is progressive enhancement; there is no JS test harness in this repo, so it is verified manually in Task 5. The filter and partial markup (the parts that matter for correctness of *content*) are unit-tested.
- If any URL name or role-grant helper differs from what a test assumes, fix the test to match the codebase's existing pattern — do not change app behaviour to fit the test.
