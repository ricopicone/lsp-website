# Render Messages Once Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render Django messages exactly once, from `core/base.html`, so that all 283 `messages.*` call sites actually reach the user, and delete the 30 per-page loops that would otherwise double-render.

**Architecture:** One new partial, `core/templates/core/_messages.html`, included from `base.html` inside `<main>` above the survey nudge. All 30 existing loops are removed in the same change, because adding without removing double-renders and removing without adding loses messages entirely. A guard test then makes it impossible to reintroduce a per-page loop.

**Tech Stack:** Django 5.2, pytest-django, Tailwind v4 + DaisyUI v5.

**Spec:** `docs/superpowers/specs/2026-07-31-messages-render-once-design.md`

## Global Constraints

- Run tests with `uv run pytest`, lint with `uv run ruff check .`. Both green before every commit.
- Serialize a test run with `-n 0` (addopts sets `-n auto`; `-p no:xdist` breaks the flag and errors).
- Python line length 100 (ruff `E`, `F`, `I`, `UP`).
- **Multi-line `{# #}` template comments are banned** (`core/test_templates.py`). Use `{% comment %}`/`{% endcomment %}`.
- Every DaisyUI class must appear **literally** in a `.html` file or the Tailwind build drops it. The canonical partial spells out `alert-error`, `alert-warning`, `alert-success`, `alert-info` in full for exactly this reason.
- Match message levels with `'x' in m.tags`, never `m.tags == 'x'`: `extra_tags` makes `m.tags` a space-separated string.
- Worktree is `/Users/picone/LSP-Web-Coordinator/lsp-website/.claude-worktrees/calm-willow`.

---

### Task 1: One canonical rendering, thirty loops removed

This is deliberately a single task. Adding the base rendering without removing
the loops double-renders every message; removing the loops without adding the
base rendering loses them. Neither half is independently shippable.

**Files:**
- Create: `core/templates/core/_messages.html`
- Modify: `core/templates/core/base.html:348-357` (inside `<main>`, above the survey nudge)
- Modify: 30 templates, listed in Step 4
- Test: `core/test_messages_render.py` (create)

**Interfaces:**
- Consumes: `django.contrib.messages.context_processors.messages`, already in `config/settings/base.py:110`.
- Produces: the partial `core/_messages.html`, expecting `messages` in context and nothing else.

- [ ] **Step 1: Write the failing tests**

Create `core/test_messages_render.py`:

```python
"""Django messages render once, from the base template (2026-07-31).

Before this, `core/base.html` rendered no messages and 30 page templates each
carried their own loop, so a `messages.success()` from a view whose template
lacked one produced nothing at all.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.urls import reverse
from PIL import Image

from accounts.models import User
from events.models import CEOrganization, Event


class _Msg:
    """Stand-in for django.contrib.messages.storage.base.Message."""

    def __init__(self, text, tags):
        self.text = text
        self.tags = tags

    def __str__(self):
        return self.text


# ---- The partial itself ------------------------------------------------


def test_each_level_maps_to_its_daisyui_class():
    html = render_to_string("core/_messages.html", {"messages": [
        _Msg("bad", "error"),
        _Msg("careful", "warning"),
        _Msg("done", "success"),
        _Msg("fyi", "info"),
    ]})
    assert "alert-error" in html
    assert "alert-warning" in html
    assert "alert-success" in html
    assert "alert-info" in html


def test_extra_tags_do_not_break_the_level_match():
    """`messages.success(request, msg, extra_tags="x")` makes tags "x success";
    an `== 'success'` test would silently miss it and fall through."""
    html = render_to_string("core/_messages.html", {"messages": [
        _Msg("done", "x success"),
    ]})
    assert "alert-success" in html
    assert "alert-info" not in html


def test_nothing_renders_without_messages():
    assert render_to_string("core/_messages.html", {"messages": []}).strip() == ""


# ---- End to end --------------------------------------------------------


def _logo():
    buf = io.BytesIO()
    Image.new("RGBA", (40, 20), (10, 20, 30, 255)).save(buf, format="PNG")
    return SimpleUploadedFile("l.png", buf.getvalue(), content_type="image/png")


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Seminar XI", slug="seminar-xi",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
        published=True, status=Event.Status.OPEN,
    )


@pytest.fixture
def faculty(db, event):
    u = User.objects.create_user(email="fac-msg@x.test")
    u.profile.is_faculty = True
    u.profile.save()
    event.add_faculty(u)
    return u


@pytest.mark.django_db
def test_a_message_reaches_a_page_that_had_no_loop(
    client, event, faculty, settings, tmp_path,
):
    """events/event_edit.html never rendered messages, so this confirmation was
    invisible before."""
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = client.post(
        reverse("events:ce_organization_add", args=[event.slug]),
        {"name": "APA", "logo": [_logo()]},
        follow=True,
    )
    assert b"Added APA and applied it to this event." in response.content


@pytest.mark.django_db
def test_a_message_renders_exactly_once(client, event, faculty, settings, tmp_path):
    """ce_organization_edit.html carried its own loop; with the base rendering
    in place it must not print twice."""
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(name="GPPA")
    from events.ce_images import normalize_logo
    org.add_logos([normalize_logo(_logo())])
    client.force_login(faculty)
    body = client.post(
        reverse("events:ce_organization_edit", args=[event.slug, org.pk]),
        {"action": "remove", "logo_id": org.logos.first().pk},
        follow=True,
    ).content.decode()
    assert body.count("An organization needs at least one logo.") == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/test_messages_render.py -q -n 0`
Expected: FAIL — `TemplateDoesNotExist: core/_messages.html` for the first three, and the two end-to-end tests fail on the missing / doubled message.

- [ ] **Step 3: Write the partial and include it**

Create `core/templates/core/_messages.html`:

```html
{% comment %}Django messages, rendered once for the whole site (2026-07-31).

Included from core/base.html. Do NOT add a per-page messages loop: a second
rendering in the same response prints every message twice. core/test_templates.py
enforces this.

Levels are matched with `in` rather than `==` because extra_tags makes m.tags a
space-separated string ("mytag success"), which `==` silently misses. Every
DaisyUI class is spelled out in full so the Tailwind scanner keeps it.
{% endcomment %}
{% if messages %}
<div class="mb-6 space-y-2">
  {% for m in messages %}
  <div role="alert" class="alert py-2 text-sm {% if 'error' in m.tags %}alert-error{% elif 'warning' in m.tags %}alert-warning{% elif 'success' in m.tags %}alert-success{% else %}alert-info{% endif %}">{{ m }}</div>
  {% endfor %}
</div>
{% endif %}
```

In `core/templates/core/base.html`, inside `<main>`, put the include **above**
the survey nudge — a message answers what the user just did, so it comes before
standing furniture. The block currently reads:

```html
  <main class="flex-1 mx-auto w-full max-w-5xl px-4 sm:px-6 py-8 sm:py-10">
    {% if show_survey_nudge %}
```

Change it to:

```html
  <main class="flex-1 mx-auto w-full max-w-5xl px-4 sm:px-6 py-8 sm:py-10">
    {% include "core/_messages.html" %}
    {% if show_survey_nudge %}
```

- [ ] **Step 4: Remove all 30 per-page loops**

The blocks differ in shape (single-line, indented, and two wrapped in a
`<div class="space-y-2">`), and the single-line ones contain inline
`{% if %}…{% endif %}` within the same line, so a line-based `sed` would cut the
wrong range. Use this depth-counting script, which tokenizes `{% if %}`,
`{% for %}`, `{% endif %}`, `{% endfor %}` and removes the balanced block:

`$SCRATCH` is this session's scratchpad directory; any writable temp dir works.

```bash
cat > $SCRATCH/strip_messages.py <<'PY'
import re
from pathlib import Path

TARGETS = """
accounts/templates/accounts/survey.html
admissions/templates/admissions/analyst/interview.html
admissions/templates/admissions/coordinator/base.html
admissions/templates/admissions/direct_admit.html
admissions/templates/admissions/review_detail.html
admissions/templates/admissions/status.html
availability/templates/availability/base.html
core/templates/core/staff/admin/board_appointments.html
core/templates/core/staff/admin/board_committees.html
core/templates/core/staff/admin/board_membership.html
core/templates/core/staff/aphorisms.html
events/templates/events/ce_organization_edit.html
events/templates/events/program_admin/base.html
formation/templates/formation/advancement_detail.html
formation/templates/formation/advancement_queue.html
formation/templates/formation/advise_queue.html
formation/templates/formation/advisee_detail.html
formation/templates/formation/advisees.html
formation/templates/formation/external_analyst_detail.html
formation/templates/formation/external_analyst_queue.html
formation/templates/formation/formation.html
payments/templates/payments/treasurer/reconcile.html
payments/templates/payments/tuition_plan_queue.html
referrals/templates/referrals/base.html
referrals/templates/referrals/respond.html
registrations/templates/registrations/register_confirm.html
registrations/templates/registrations/registrar/base.html
suggestions/templates/suggestions/triage.html
workgroups/templates/workgroups/_tab_decisions.html
workgroups/templates/workgroups/_tab_files.html
""".split()

TAG = re.compile(r"\{%-?\s*(if|for|endif|endfor)\b")

for rel in TARGETS:
    p = Path(rel)
    text = p.read_text(encoding="utf-8")
    start = text.index("{% if messages %}")
    depth, i = 0, start
    while True:
        m = TAG.search(text, i)
        if m is None:
            raise SystemExit(f"unbalanced block in {rel}")
        depth += 1 if m.group(1) in ("if", "for") else -1
        end = text.index("%}", m.end()) + 2
        i = end
        if depth == 0:
            break
    # Swallow the surrounding blank line so we don't leave a double gap.
    line_start = text.rfind("\n", 0, start) + 1
    line_end = i
    while line_end < len(text) and text[line_end] in " \t":
        line_end += 1
    if text[line_end:line_end + 1] == "\n":
        line_end += 1
    if text[line_end:line_end + 1] == "\n":
        line_end += 1
    p.write_text(text[:line_start] + text[line_end:], encoding="utf-8")
    print("stripped", rel)
PY
uv run python $SCRATCH/strip_messages.py
```

- [ ] **Step 5: Confirm nothing is left and read the diff**

Run: `grep -rn "for m in messages\|for message in messages" --include=*.html accounts admissions availability cartels committees core events formation notifications parletre payments referrals registrations suggestions workgroups workinggroups`

Expected: exactly one hit, `core/templates/core/_messages.html`.

Then run `git diff --stat` and expect 31 changed templates. Skim
`git diff workgroups/templates/workgroups/_tab_files.html` specifically: it is
one of the two whose block was wrapped in `<div class="space-y-2">`, so it is
the likeliest place for the script to have left a stray `</div>`. Confirm the
tag balance looks right.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest core/test_messages_render.py -q -n 0`
Expected: PASS, 5 tests.

- [ ] **Step 7: Run the full suite and lint**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all green. Any failure here is most likely a template that the script
left with unbalanced tags, which surfaces as a `TemplateSyntaxError` naming the
file.

- [ ] **Step 8: Rebuild the CSS and look at a page**

Run: `npm run build:css`

Start the server (`uv run python manage.py runserver 8912 --noreload`), sign in,
and perform an action that sets a message — e.g. save an event edit — then
confirm the confirmation appears once, at the top of the content area, in both
light and dark themes.

- [ ] **Step 9: Commit**

```bash
git add core/templates/core/_messages.html core/templates/core/base.html core/test_messages_render.py accounts admissions availability core events formation payments referrals registrations suggestions workgroups
git commit -m "fix: render Django messages once, from the base template"
```

---

### Task 2: Make the loop impossible to reintroduce

**Files:**
- Modify: `core/test_templates.py` (add `.claude-worktrees` to `EXCLUDE_DIRS`; append the guard test)
- Modify: `CLAUDE.md` (one line under the layout/conventions section)

**Interfaces:**
- Consumes: `core/test_templates.py::_template_files()` and `EXCLUDE_DIRS` from the existing module; `core/_messages.html` from Task 1.
- Produces: nothing other code depends on.

- [ ] **Step 1: Write the failing test**

Append to `core/test_templates.py`:

```python
def test_only_the_shared_partial_renders_messages():
    """Messages render once, from core/_messages.html via core/base.html.

    A second loop in a page template prints every message twice, and the habit
    that produced 30 of them was copying a neighbouring template.
    """
    offenders = []
    for path in _template_files():
        if path.name == "_messages.html":
            continue
        text = path.read_text(encoding="utf-8")
        if "for m in messages" in text or "for message in messages" in text:
            offenders.append(str(path.relative_to(Path(settings.BASE_DIR))))
    assert not offenders, (
        "Messages are rendered once, by core/_messages.html (included from "
        "core/base.html). Remove the loop from:\n  " + "\n  ".join(offenders)
    )
```

- [ ] **Step 2: Run it to see it pass, then prove it can fail**

Run: `uv run pytest core/test_templates.py -q -n 0`
Expected: PASS (Task 1 removed every loop).

A test that cannot fail is worthless, so prove it bites:

```bash
printf '\n{%% if messages %%}{%% for m in messages %%}<p>{{ m }}</p>{%% endfor %%}{%% endif %%}\n' >> events/templates/events/event_edit.html
uv run pytest core/test_templates.py::test_only_the_shared_partial_renders_messages -q -n 0
git checkout events/templates/events/event_edit.html
```

Expected: FAIL naming `events/templates/events/event_edit.html`, then the
checkout restores it. Re-run the test to confirm it passes again.

- [ ] **Step 3: Stop the guard scanning sibling worktrees**

`_template_files()` walks `settings.BASE_DIR`, and this repo keeps sibling
worktrees under `.claude-worktrees/`. Run from the **main** checkout, the guard
would scan every other worktree — all of them on older branches that still carry
the 30 loops — and fail for reasons having nothing to do with the tree under
test. (The existing multi-line-comment test has the same exposure and has only
been passing by luck.)

In `core/test_templates.py`, change:

```python
EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "node_modules", ".claude",
    "staticfiles", "htmlcov", "dist", "build",
}
```

to:

```python
EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "node_modules", ".claude", ".claude-worktrees",
    "staticfiles", "htmlcov", "dist", "build",
}
```

- [ ] **Step 4: Verify the guard from the main checkout**

Run: `cd /Users/picone/LSP-Web-Coordinator/lsp-website && uv run pytest core/test_templates.py -q -n 0`
Expected: PASS. Without Step 3 this fails with a long list of paths under
`.claude-worktrees/`, which is the proof the exclusion was needed.

Return to the worktree afterwards.

- [ ] **Step 5: Record the convention**

In `CLAUDE.md`, in the bulleted conventions under "Layout and conventions",
add:

```markdown
- **Django messages render once**, from `core/templates/core/_messages.html`,
  included by `core/base.html`. Never add a per-page messages loop: a second
  rendering prints every message twice. `core/test_templates.py` enforces this.
```

- [ ] **Step 6: Run the full suite and lint**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add core/test_templates.py CLAUDE.md
git commit -m "test: pin messages to the shared partial, and skip sibling worktrees"
```

---

## Notes for the reviewer

- **Task 1 is intentionally not split.** The base include and the 30 deletions are two halves of one change; either alone leaves the site broken (doubled messages, or none).
- **Four of the 30 were quietly wrong** and are fixed by consolidation: `registrations/register_confirm.html` painted *every* message `alert-error`; `referrals/respond.html` painted every message `alert-success`; `admissions/direct_admit.html` and `core/staff/aphorisms.html` built the class dynamically as `alert-{{ m.tags }}`, which the Tailwind scanner cannot see and which breaks outright once `extra_tags` is used.
- **The biggest behavioural win is the treasurer console:** `payments/views.py` makes 89 message calls and only one of its eight tabs rendered them.
- **Not done, per the spec:** auto-dismiss or toasts, and any audit of the 283 call sites for wording or level.
