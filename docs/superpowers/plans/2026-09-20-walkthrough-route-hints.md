# Walkthrough Route Hints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A walkthrough step can carry a route of hops, and on every page the card points at the one element that takes the member to the next hop of their first unfinished step.

**Architecture:** `Hop` rows live on `ChecklistTask.route` in `core/checklists.py`. At render time each task resolves the hop matching the current request (server-side, the viewer's own slugs), and `base.html` emits one hidden popover per task that has one. The card's existing client script, which alone knows which manual steps are ticked, picks the first unfinished task's popover and activates it through the existing `lspTourHint`, extended with session-scoped dismissal and a minimized-card guard. Anchors are `data-tour` attributes added to seven templates.

**Tech Stack:** Django 5.2 templates, the existing `lspTourHint` vanilla JS in `base.html`, pytest-django.

**Spec:** `docs/superpowers/specs/2026-09-20-walkthrough-route-hints-design.md`

## Global Constraints

- Member-facing copy uses commas, never em dashes.
- No new JS files: the hint script already lives inline in `base.html` (Tailwind scans templates only; classes emitted from JS must already exist in a template).
- Only the first unfinished step shows a hop; a hop whose selector matches nothing renders nothing.
- "Got it" dismisses a hop for the session (`sessionStorage`), never forever.
- A minimized card (`sessionStorage["lsp-wt-min"] === "1"`) shows no hop.
- A step may carry `route` or `hint_selector`, not both.

---

### Task 1: `Hop` and `ChecklistTask.route`

**Files:**
- Modify: `core/checklists.py` (dataclasses near the top; `resolved()`)
- Test: `core/test_checklists.py`

**Interfaces:**
- Produces: `Hop(page, selector, text, placement="below")` where `page` and `selector` are each a `str` or a callable `(request) -> str | None`. `page == "*"` matches every page. A page string with `?` must match `request.path + "?" + query` exactly; without `?` it matches `request.path` only.
- Produces: `ChecklistTask.route: tuple[Hop, ...]`, `ChecklistTask.hop_for(request) -> dict | None` returning `{"selector", "text", "placement", "index"}` for the first matching hop, and `resolved()` gaining `"hop": <that or None>`.
- `ChecklistTask.__post_init__` raises `ValueError` if both `route` and `hint_selector` are set.

- [ ] **Step 1: Write the failing tests** (append to `core/test_checklists.py`)

```python
# --- Route hints (task #749, route-hints spec) ------------------------------

def _rf_request(rf, user, path):
    request = rf.get(path)
    request.user = user
    return request


def test_hop_matches_path_only_or_path_and_query(rf, db):
    from core.checklists import Hop

    user = get_user_model().objects.create_user(email="h@example.com", password="x")
    path_only = Hop(page="/groups/x/", selector="[data-tour=a]", text="A")
    with_query = Hop(page="/groups/x/?tab=roster", selector="[data-tour=b]", text="B")
    assert path_only.matches(_rf_request(rf, user, "/groups/x/?tab=meet")) is True
    assert with_query.matches(_rf_request(rf, user, "/groups/x/?tab=meet")) is False
    assert with_query.matches(_rf_request(rf, user, "/groups/x/?tab=roster")) is True
    assert Hop(page="*", selector="[data-tour=c]", text="C").matches(
        _rf_request(rf, user, "/anything/")) is True


def test_task_hop_for_picks_the_first_matching_hop(rf, db):
    from core.checklists import ChecklistTask, Hop

    user = get_user_model().objects.create_user(email="h2@example.com", password="x")
    task = ChecklistTask(id="t", label="T", detail="", manual=True, route=(
        Hop(page="/groups/x/?tab=roster", selector="[data-tour=code]", text="Here."),
        Hop(page="/groups/x/", selector="[data-tour=ws-tab-roster]", text="Roster tab."),
        Hop(page="*", selector="[data-tour=avatar]", text="Open your menu."),
    ))
    assert task.hop_for(_rf_request(rf, user, "/groups/x/?tab=roster"))["selector"] == "[data-tour=code]"
    assert task.hop_for(_rf_request(rf, user, "/groups/x/?tab=meet"))["selector"] == "[data-tour=ws-tab-roster]"
    assert task.hop_for(_rf_request(rf, user, "/"))["index"] == 2
    assert task.resolved(user, _rf_request(rf, user, "/"))["hop"]["text"] == "Open your menu."


def test_hop_page_and_selector_may_be_callables(rf, db):
    from core.checklists import ChecklistTask, Hop

    user = get_user_model().objects.create_user(email="h3@example.com", password="x")
    task = ChecklistTask(id="t2", label="T", detail="", manual=True, route=(
        Hop(page=lambda r: "/groups/mine/", selector=lambda r: "[data-tour-slug=mine]", text="Yours."),
    ))
    assert task.hop_for(_rf_request(rf, user, "/groups/mine/"))["selector"] == "[data-tour-slug=mine]"
    assert task.hop_for(_rf_request(rf, user, "/groups/other/")) is None


def test_hop_with_unresolvable_page_never_matches(rf, db):
    from core.checklists import ChecklistTask, Hop

    user = get_user_model().objects.create_user(email="h4@example.com", password="x")
    task = ChecklistTask(id="t3", label="T", detail="", manual=True, route=(
        Hop(page=lambda r: None, selector="[data-tour=x]", text="X"),
    ))
    assert task.hop_for(_rf_request(rf, user, "/")) is None


def test_task_refuses_both_route_and_hint():
    from core.checklists import ChecklistTask, Hop

    with pytest.raises(ValueError):
        ChecklistTask(id="t4", label="T", detail="", hint_selector="#x",
                      route=(Hop(page="*", selector="#y", text="Y"),))
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest core/test_checklists.py -q -n 0 -k "hop or refuses_both"`
Expected: FAIL with `ImportError: cannot import name 'Hop'`.

- [ ] **Step 3: Implement**

In `core/checklists.py`, after `_no_url`, add:

```python
def _call_or_value(value, request):
    return value(request) if callable(value) else value


@dataclass(frozen=True)
class Hop:
    """One leg of a route: on ``page``, pulse ``selector`` and say ``text``.

    ``page`` / ``selector`` may be callables of the request so a route can
    name the viewer's own seminar. ``page == "*"`` matches everywhere and is
    the fallback that points back at the menu from any page off the route.
    A page string with a query must match path+query; without, path only.
    """

    page: object          # str | Callable[[request], str | None]
    selector: object      # str | Callable[[request], str | None]
    text: str
    placement: str = "below"

    def matches(self, request) -> bool:
        try:
            page = _call_or_value(self.page, request)
        except NoReverseMatch:
            return False
        if not page:
            return False
        if page == "*":
            return True
        if "?" in page:
            query = request.META.get("QUERY_STRING", "")
            here = request.path + ("?" + query if query else "")
            return here == page
        return request.path == page

    def resolved(self, request, index: int) -> dict | None:
        try:
            selector = _call_or_value(self.selector, request)
        except NoReverseMatch:
            return None
        if not selector:
            return None
        return {"selector": selector, "text": self.text,
                "placement": self.placement, "index": index}
```

On `ChecklistTask`, add the field `route: tuple = ()` after `hint_key`, then:

```python
    def __post_init__(self):
        if self.route and self.hint_selector:
            raise ValueError(f"task {self.id}: a route or a hint, not both")

    def hop_for(self, request) -> dict | None:
        """The first hop of this task's route that matches the current page."""
        if request is None:
            return None
        for index, hop in enumerate(self.route):
            if hop.matches(request):
                return hop.resolved(request, index)
        return None
```

and in `resolved()` add `"hop": self.hop_for(request),` to the returned dict.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest core/test_checklists.py -q -n 0`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add core/checklists.py core/test_checklists.py
git commit -m "feat(core): a walkthrough step can carry a route of hops (task #749)"
```

---

### Task 2: The faculty walkthrough's routes

**Files:**
- Modify: `core/checklists.py` (`_faculty_walkthrough` and helpers above it)
- Test: `core/test_checklists.py`

**Interfaces:**
- Consumes: `Hop`, `ChecklistTask.route`, `_my_offering`, `_fac_workspace_url`, `_fac_roster_url`, `_fac_edit_url`, `_fac_joining_url`, `_my_groups_url`.
- Produces: helper `_fac_workspace_path(request)` (the Workspace path with no query, or None) and `_fac_card_selector(request)` (`[data-tour=group-card][data-tour-slug="<slug>"]`, or None); the constant `AVATAR_HOP` text.
- Selectors used (Task 3 adds the anchors): `[data-tour=avatar]`, `[data-tour=my-lsp-groups]`, `[data-tour=my-lsp-room]`, `[data-tour=group-card][data-tour-slug="…"]`, `[data-tour=ws-tab-roster]`, `[data-tour=ws-tab-meet]`, `[data-tour=edit-event]`, `[data-tour=registration-status]`, `[data-tour=generate-code]`, `[data-tour=joining-instructions]`, `[data-tour=meet-system-check]`.

- [ ] **Step 1: Write the failing tests** (append)

```python
@pytest.mark.django_db
def test_faculty_routes_point_at_the_viewers_own_seminar(rf, faculty_user):
    from events.models import Event
    from workgroups.models import WorkgroupMembership

    ev = _offering("routed-seminar", Event.Type.SEMINAR, (2026, 9, 1), (2999, 5, 1))
    _lead(ev, faculty_user, WorkgroupMembership.Role.FACULTY)
    slug = ev.workgroup.slug
    tasks = {t.id: t for t in get_checklist("faculty").tasks}

    # Off the route: every step points at the avatar menu.
    hop = tasks["fac_roster"].hop_for(_rf_request(rf, faculty_user, "/guides/faculty/"))
    assert hop["selector"] == "[data-tour=avatar]"
    # On My LSP → Groups: the viewer's own card.
    hop = tasks["fac_roster"].hop_for(_rf_request(rf, faculty_user, "/formation/?tab=groups"))
    assert hop["selector"] == f'[data-tour=group-card][data-tour-slug="{slug}"]'
    # On the Workspace (any tab): the Roster tab.
    hop = tasks["fac_roster"].hop_for(_rf_request(rf, faculty_user, f"/groups/{slug}/?tab=meet"))
    assert hop["selector"] == "[data-tour=ws-tab-roster]"
    # On the Roster tab: the code form and the joining button.
    roster = _rf_request(rf, faculty_user, f"/groups/{slug}/?tab=roster")
    assert tasks["fac_code"].hop_for(roster)["selector"] == "[data-tour=generate-code]"
    assert tasks["fac_joining"].hop_for(roster)["selector"] == "[data-tour=joining-instructions]"
    # Edit event: from the Workspace, the button; on the edit page, the panel.
    assert tasks["fac_edit"].hop_for(roster)["selector"] == "[data-tour=edit-event]"
    edit = _rf_request(rf, faculty_user, f"/events/{ev.slug}/edit/")
    assert tasks["fac_status"].hop_for(edit)["selector"] == "[data-tour=registration-status]"
    # Video: the Meet tab, then its test link.
    assert tasks["fac_video"].hop_for(roster)["selector"] == "[data-tour=ws-tab-meet]"
    meet = _rf_request(rf, faculty_user, f"/groups/{slug}/?tab=meet")
    assert tasks["fac_video"].hop_for(meet)["selector"] == "[data-tour=meet-system-check]"
    # The private room is reached from My LSP.
    hub = _rf_request(rf, faculty_user, "/formation/?tab=groups")
    assert tasks["fac_room"].hop_for(hub)["selector"] == "[data-tour=my-lsp-room]"


@pytest.mark.django_db
def test_faculty_routes_without_an_offering_only_point_at_the_menu(rf, faculty_user):
    tasks = {t.id: t for t in get_checklist("faculty").tasks}
    hop = tasks["fac_roster"].hop_for(_rf_request(rf, faculty_user, "/formation/?tab=groups"))
    assert hop["selector"] == "[data-tour=avatar]"


def test_every_faculty_step_has_a_fallback_hop():
    for task in get_checklist("faculty").tasks:
        assert task.route, task.id
        assert task.route[-1].page == "*", task.id
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest core/test_checklists.py -q -n 0 -k "routes or fallback_hop"`
Expected: FAIL (`hop_for` returns None / `route` empty).

- [ ] **Step 3: Implement** in `core/checklists.py`, above `_faculty_walkthrough`:

```python
def _fac_workspace_path(request):
    event = _my_offering(request)
    if event is None or event.workgroup_id is None:
        return None
    return _rev("workgroups:detail", event.workgroup.slug)


def _fac_card_selector(request):
    event = _my_offering(request)
    if event is None or event.workgroup_id is None:
        return None
    return f'[data-tour=group-card][data-tour-slug="{event.workgroup.slug}"]'


def _fac_meet_url(request):
    path = _fac_workspace_path(request)
    return f"{path}?tab=meet" if path else None


MENU_TEXT = "Open your menu, then <strong>My LSP</strong>, then <strong>Groups</strong>."
AVATAR_HOP = Hop(page="*", selector="[data-tour=avatar]", text=MENU_TEXT)
CARD_HOP = Hop(page=_my_groups_url, selector=_fac_card_selector,
               text="<strong>This is your seminar.</strong> Open it.")
ROSTER_TAB_HOP = Hop(page=_fac_workspace_path, selector="[data-tour=ws-tab-roster]",
                     text="Your roster, approvals, and codes live on the <strong>Roster</strong> tab.")
```

Then give each task a `route=`:

```python
        # fac_workspace
        route=(CARD_HOP, AVATAR_HOP),
        # fac_roster
        route=(ROSTER_TAB_HOP, CARD_HOP, AVATAR_HOP),
        # fac_edit
        route=(Hop(page=_fac_workspace_path, selector="[data-tour=edit-event]",
                   text="<strong>Edit event</strong> opens the page's content."),
               CARD_HOP, AVATAR_HOP),
        # fac_status
        route=(Hop(page=_fac_edit_url, selector="[data-tour=registration-status]",
                   text="Close registration here. The button then reads <strong>Open registration</strong>, so you can reopen."),
               Hop(page=_fac_workspace_path, selector="[data-tour=edit-event]",
                   text="<strong>Edit event</strong>, then the Registration panel at the bottom."),
               CARD_HOP, AVATAR_HOP),
        # fac_code
        route=(Hop(page=_fac_roster_url, selector="[data-tour=generate-code]",
                   text="Mint a code here. It appears under <strong>Existing codes</strong>."),
               ROSTER_TAB_HOP, CARD_HOP, AVATAR_HOP),
        # fac_joining
        route=(Hop(page=_fac_roster_url, selector="[data-tour=joining-instructions]",
                   text="<strong>Email joining instructions</strong> shows the whole email before anything goes."),
               ROSTER_TAB_HOP, CARD_HOP, AVATAR_HOP),
        # fac_video
        route=(Hop(page=_fac_meet_url, selector="[data-tour=meet-system-check]",
                   text="<strong>Test your setup</strong> opens a throwaway room for camera and microphone."),
               Hop(page=_fac_workspace_path, selector="[data-tour=ws-tab-meet]",
                   text="The <strong>Meet</strong> tab has the test link."),
               CARD_HOP, AVATAR_HOP),
        # fac_room
        route=(Hop(page=_rev_formation_path, selector="[data-tour=my-lsp-room]",
                   text="Your private room is the <strong>Meeting room</strong> tab."),
               Hop(page="*", selector="[data-tour=avatar]",
                   text="Open your menu, then <strong>My LSP</strong>, then <strong>Meeting room</strong>.")),
```

where `_rev_formation_path = lambda r: _rev("formation:formation")` (path only, so it matches every hub tab). Note `_fac_edit_url` and `_fac_roster_url` already exist; `_fac_roster_url` carries `?tab=roster` so it matches the roster tab exactly, and `_fac_workspace_path` matches any tab.

- [ ] **Step 4: Run** `uv run pytest core/test_checklists.py -q -n 0` — expected: pass.

- [ ] **Step 5: Commit** `git commit -am "feat(core): routes on the faculty walkthrough (task #749)"`

---

### Task 3: The anchors

**Files:**
- Modify: `core/templates/core/base.html` (avatar button ~line 249; My LSP links ~line 277)
- Modify: `formation/templates/formation/formation.html` (tab loop, line 23)
- Modify: `workgroups/templates/workgroups/_my_group_card.html` (line 6)
- Modify: `workgroups/templates/workgroups/detail.html` (tab loop line 94; Edit event line 83)
- Modify: `events/templates/events/_faculty_tools.html` (joining button line 59; code form line 117)
- Modify: `events/templates/events/_registration_status.html` (the form element)
- Modify: `workgroups/templates/workgroups/_tab_meet.html` (line 31)
- Test: `core/test_tour_anchors.py` (create)

**Interfaces:**
- Produces the `data-tour` attributes listed in Task 2.

- [ ] **Step 1: Write the failing test** (`core/test_tour_anchors.py`)

```python
"""The data-tour anchors route hints point at. A refactor that drops one
fails here rather than in a training (route-hints spec)."""

from __future__ import annotations

from datetime import date

import pytest
from django.contrib.auth import get_user_model

from events.models import Event
from workgroups.models import WorkgroupMembership


@pytest.fixture
def faculty(db):
    user = get_user_model().objects.create_user(email="anchor@example.com", password="x")
    ev = Event.objects.create(
        title="Anchored", slug="anchored", event_type=Event.Type.SEMINAR,
        start_date=date(2026, 9, 1), end_date=date(2999, 5, 1), published=True,
        status=Event.Status.OPEN,
    )
    ev.ensure_workgroup()
    WorkgroupMembership.objects.create(
        workgroup=ev.workgroup, user=user, role=WorkgroupMembership.Role.FACULTY,
        start_date=date(2026, 9, 1),
    )
    return user, ev


def _get(client, user, url):
    client.force_login(user)
    resp = client.get(url)
    assert resp.status_code == 200, url
    return resp.content.decode()


def test_header_carries_avatar_and_my_lsp_anchors(client, faculty):
    user, _ = faculty
    body = _get(client, user, "/")
    assert 'data-tour="avatar"' in body
    assert 'data-tour="my-lsp-groups"' in body


def test_my_lsp_hub_and_group_cards_carry_anchors(client, faculty):
    user, ev = faculty
    body = _get(client, user, "/formation/?tab=groups")
    assert 'data-tour="my-lsp-room"' in body or 'data-tour="my-lsp-groups"' in body
    assert f'data-tour="group-card" data-tour-slug="{ev.workgroup.slug}"' in body


def test_workspace_carries_tab_edit_and_faculty_tool_anchors(client, faculty):
    user, ev = faculty
    wg = ev.workgroup.slug
    body = _get(client, user, f"/groups/{wg}/?tab=roster")
    assert 'data-tour="ws-tab-roster"' in body
    assert 'data-tour="edit-event"' in body
    assert 'data-tour="generate-code"' in body
    assert 'data-tour="joining-instructions"' in body
    assert 'data-tour="registration-status"' in body


def test_edit_page_carries_registration_status_anchor(client, faculty):
    user, ev = faculty
    body = _get(client, user, f"/events/{ev.slug}/edit/")
    assert 'data-tour="registration-status"' in body


def test_meet_tab_carries_system_check_anchor(client, faculty, settings):
    settings.DAILY_ENABLED = True
    settings.DAILY_API_KEY = "k"
    settings.DAILY_DOMAIN = "lsp.daily.co"
    user, ev = faculty
    body = _get(client, user, f"/groups/{ev.workgroup.slug}/?tab=meet")
    assert 'data-tour="meet-system-check"' in body
```

- [ ] **Step 2: Run** `uv run pytest core/test_tour_anchors.py -q -n 0` — expected: FAIL on every assertion.

- [ ] **Step 3: Add the attributes**

- `base.html` avatar: on the `<div tabindex="0" role="button" ... aria-label="Account menu">` add `data-tour="avatar"`.
- `base.html` My LSP loop: `<li><a href="{% url 'formation:formation' %}?tab={{ key }}" class="pl-6 text-sm" data-tour="my-lsp-{{ key }}">{{ label }}</a></li>`.
- `formation.html` tabs: add `data-tour="my-lsp-{{ key }}"` to the `<a href="?tab={{ key }}" role="tab"`.
- `_my_group_card.html`: `<a href="{{ r.url }}" class="font-medium link link-hover" data-tour="group-card" data-tour-slug="{{ r.workgroup.slug }}">`.
- `detail.html` tabs: add `data-tour="ws-tab-{{ key }}"`; Edit event button: add `data-tour="edit-event"`.
- `_faculty_tools.html`: joining button add `data-tour="joining-instructions"`; the code `<form ... action="{% url 'events:generate_code' ...` add `data-tour="generate-code"`.
- `_registration_status.html`: the `<form` add `data-tour="registration-status"`.
- `_tab_meet.html`: the test link add `data-tour="meet-system-check"`.

If the Meet tab test in Step 1 cannot render without Daily (it 404s or the link is behind a flag), read `workgroups/views.py:445` and set what that branch needs; keep the assertion.

- [ ] **Step 4: Run** `uv run pytest core/test_tour_anchors.py -q -n 0` — expected: pass.

- [ ] **Step 5: Commit** `git add -A core/test_tour_anchors.py core/templates formation/templates workgroups/templates events/templates && git commit -m "feat: data-tour anchors for route hints (task #749)"`

---

### Task 4: Rendering the hop

**Files:**
- Create: `core/templates/core/_tour_hop.html`
- Modify: `core/templates/core/base.html` (`lspTourHint`; the card script; include the partial after the card)
- Test: `core/test_preview_tour.py`

**Interfaces:**
- Consumes: `preview_tour_tasks[*]["hop"]` from Task 1 (present in the context processor's output already, since it comes from `resolved()`).
- Produces: one `<div data-wt-hop="<task id>" ...>` popover per task with a hop, hidden; the card script activates the first unfinished one via `lspTourHint({..., session: true, minimizedKey: "lsp-wt-min"})`.

- [ ] **Step 1: Write the failing test** (append to `core/test_preview_tour.py`)

```python
@pytest.mark.django_db
def test_card_renders_a_hidden_hop_per_step_that_has_one(client, settings):
    settings.PREVIEW_TOUR_ENABLED = True
    settings.PREVIEW_TOUR_PUBLIC = True
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(email="hop@example.com", password="x")
    client.force_login(user)
    client.cookies["lsp_walkthrough"] = "faculty"
    body = client.get("/guides/faculty/").content.decode()
    # Off the route, every faculty step's hop is the avatar fallback.
    assert 'data-wt-hop="fac_workspace"' in body
    assert 'data-wt-hop="fac_room"' in body
    assert 'data-hop-selector="[data-tour=avatar]"' in body
    assert "lsp-hop-fac_workspace" in body
    assert "Open your menu" in body
```

- [ ] **Step 2: Run** `uv run pytest core/test_preview_tour.py -q -n 0 -k hidden_hop` — expected: FAIL.

- [ ] **Step 3: Implement**

`core/templates/core/_tour_hop.html`:

```django
{% comment %}
One route hop's popover, hidden. Rendered once per step that has a hop on this
page; the card script activates the first unfinished one (only the client
knows which manual steps are ticked). See the route-hints spec.
{% endcomment %}
<div id="lsp-hop-{{ task.id }}" data-wt-hop="{{ task.id }}"
     data-hop-selector="{{ task.hop.selector }}" data-hop-placement="{{ task.hop.placement }}"
     data-hop-index="{{ task.hop.index }}"
     class="hidden fixed z-50 w-64 card bg-primary text-primary-content shadow-xl"
     role="dialog" aria-label="Tip">
  <div class="card-body p-3 gap-2">
    <p class="text-sm leading-snug">{{ task.hop.text|safe }}</p>
    <div class="text-right">
      <button type="button" class="btn btn-xs lsp-tour-ok">Got it</button>
    </div>
  </div>
  <span class="lsp-tour-arrow" aria-hidden="true"></span>
</div>
```

In `base.html`, after the closing `</div>` of `#lsp-preview-tour`:

```django
  {% for task in preview_tour_tasks %}{% if task.hop %}{% include "core/_tour_hop.html" with task=task %}{% endif %}{% endfor %}
```

In `lspTourHint`, support session-scoped dismissal and the minimized guard. Change the top of the function to:

```javascript
    window.lspTourHint = function (opts) {
      var btn = document.querySelector(opts.target);
      var pop = document.querySelector(opts.popover);
      if (!btn || !pop) return;
      var store = opts.session ? sessionStorage : localStorage;
      try { if (store.getItem(opts.key) === "done") return; } catch (e) {}
      try { if (opts.minimizedKey && sessionStorage.getItem(opts.minimizedKey) === "1") return; } catch (e) {}
```

and in `dismiss()` replace `localStorage.setItem(opts.key, "done")` with `store.setItem(opts.key, "done")`.

In the card's manual-tick script, after the scroll-to-first-unfinished block, add:

```javascript
      // Route hint: activate the hop of the first unfinished step that has
      // one on this page. Server-side "done" ignores manual ticks, so this
      // choice has to be made here.
      var hopTask = null;
      root.querySelectorAll("li[data-wt-task]").forEach(function (li) {
        if (hopTask) return;
        var tick = li.querySelector(".lsp-tour-tick");
        if (tick && !tick.classList.contains("lsp-tour-tick--done")) hopTask = li.getAttribute("data-wt-task");
      });
      var pop = hopTask && document.querySelector('[data-wt-hop="' + hopTask + '"]');
      if (pop && window.lspTourHint) lspTourHint({
        target: pop.getAttribute("data-hop-selector"),
        popover: "#" + pop.id,
        key: "lsp-wt-hop:" + wid + ":" + hopTask + ":" + pop.getAttribute("data-hop-index"),
        placement: pop.getAttribute("data-hop-placement"),
        session: true,
        minimizedKey: "lsp-wt-min",
      });
```

In `restart()`, also clear hop dismissals: iterate `sessionStorage` keys starting with `"lsp-wt-hop:" + wid + ":"` and remove them (wrap in try/catch).

Note the script order: the manual-tick script runs at body end, after `lspTourHint` is defined, so no `DOMContentLoaded` wrapper is needed.

- [ ] **Step 4: Run** `uv run pytest core/test_preview_tour.py core/test_checklists.py core/test_templates.py -q -n 0` — expected: pass (`core/test_templates.py` enforces the single-line `{# #}` rule; the partial uses `{% comment %}`).

- [ ] **Step 5: Commit** `git add core/templates/core/_tour_hop.html core/templates/core/base.html core/test_preview_tour.py && git commit -m "feat(core): the card points at the next hop of the first unfinished step (task #749)"`

---

### Task 5: Full suite, deploy, browser verification

- [ ] **Step 1:** `uv run ruff check . && uv run pytest -q` — expected: all green.
- [ ] **Step 2:** Add a status-log entry to `CLAUDE.md` under the task #749 entry (what shipped, the server/client split for choosing the hop, and that the three older single-hint walkthroughs are untouched). Commit.
- [ ] **Step 3:** `git push origin HEAD:main`; wait for the Deploy run to go green (`gh run list --repo ricopicone/lsp-website --limit 1`).
- [ ] **Step 4:** In the browser as Rico with the faculty walkthrough active and all steps reset (Start over on the guide): on the guide page the avatar pulses; open My LSP → Groups, the sandbox card pulses; open it, the Roster tab pulses; open it, step 2 ticks and the Edit event button pulses (step 3). Minimize the card on any page: no popover. "Got it" hides the hop; reload: still hidden; Start over: back.
- [ ] **Step 5:** Update the run-of-show doc's "Before you start" to say the card also points at what to click next, and the task briefing.
