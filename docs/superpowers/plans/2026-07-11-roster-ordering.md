# Roster Ordering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Order every group roster (About page Board/Program Committee, committee & workgroup pages) leaders-first by a fixed role precedence, then alphabetically by last name.

**Architecture:** Add a role→rank map on `WorkgroupMembership` and apply it at the single roster chokepoint `Workgroup.active_members()` (DB-level `Case/When` ordering) plus `Workgroup.participants()` (Python list sort with a shared key). Pure ordering rule — no schema change, no migration. All roster surfaces read through these two methods, so they inherit ordering for free.

**Tech Stack:** Django 5.2, Python 3.10+, pytest-django, ruff.

## Global Constraints

- No new DB field and no migration — this is an ordering rule, not stored data.
- Use `models.Case` / `models.When` / `models.Value` / `models.IntegerField` (already imported via `from django.db import models`) — do **not** add new imports.
- Roles `MEMBER`, `FACULTY`, `WEB_COORDINATOR`, and any future/unlisted role use the default "everyone-else" rank (`ROSTER_DEFAULT_RANK = 50`); they are NOT distinct officer positions.
- Rank table: `CHAIR`=1, `CO_CHAIR`=2, `SECRETARY`=3, `TREASURER`=4, `ORGANIZER`=5, `REFERRAL_COORDINATOR`=6, `APPLICATIONS_COORDINATOR`=7, `ADMIN_ASSISTANT`=8, default=50, `PLUS_ONE`=99.
- Within any rank, tie-break by `last_name` then `first_name`, case-insensitively.
- Keep `pytest` green and `ruff check .` clean.
- Do NOT change `OFFICER_TITLES` relabeling or `LEAD_ROLES`.

---

### Task 1: Rank map + ordered `active_members()`

**Files:**
- Modify: `workgroups/models.py` — add `ROLE_RANK` + `ROSTER_DEFAULT_RANK` class attrs on `WorkgroupMembership` (after the `LEAD_ROLES` definition, ~line 834); add module-level `roster_rank(role)` helper; rewrite `Workgroup.active_members()` (lines 282-294).
- Test: `workgroups/tests.py` (append a new section; reuse existing `_user` / `_wg` helpers).

**Interfaces:**
- Consumes: existing `WorkgroupMembership.Role` (TextChoices), `_user(email, role=, is_staff=, first=, last=)`, `_wg(**kwargs)` from `workgroups/tests.py`.
- Produces:
  - `WorkgroupMembership.ROLE_RANK: dict[str, int]` and `WorkgroupMembership.ROSTER_DEFAULT_RANK: int`.
  - Module-level `roster_rank(role: str) -> int` in `workgroups/models.py`.
  - `Workgroup.active_members()` now returns a queryset ordered by `(_role_rank, user__last_name, user__first_name)`.

- [ ] **Step 1: Write the failing test**

Append to `workgroups/tests.py`:

```python
# ---- Roster ordering (task #417) ---------------------------------------

def _board():
    return _wg(kind=Workgroup.Kind.COMMITTEE, name="Board")


def _add(wg, email, role, last, first="A"):
    u = _user(email, first=first, last=last)
    WorkgroupMembership.objects.create(
        workgroup=wg, user=u, role=role, start_date=datetime.date(2026, 1, 1)
    )
    return u


def test_active_members_orders_officers_then_alphabetical():
    wg = _board()
    Role = WorkgroupMembership.Role
    # Added in deliberately scrambled order.
    _add(wg, "m2@x.test", Role.MEMBER, "Young")
    _add(wg, "treas@x.test", Role.TREASURER, "Nkosi")
    _add(wg, "chair@x.test", Role.CHAIR, "Zimmer")
    _add(wg, "m1@x.test", Role.MEMBER, "Adams")
    _add(wg, "sec@x.test", Role.SECRETARY, "Baker")
    _add(wg, "vice@x.test", Role.CO_CHAIR, "Owens")
    order = [m.user.last_name for m in wg.active_members()]
    assert order == ["Zimmer", "Owens", "Baker", "Nkosi", "Adams", "Young"]


def test_active_members_same_role_alphabetical():
    wg = _board()
    Role = WorkgroupMembership.Role
    _add(wg, "cc2@x.test", Role.CO_CHAIR, "Vance")
    _add(wg, "cc1@x.test", Role.CO_CHAIR, "Ng")
    order = [m.user.last_name for m in wg.active_members()]
    assert order == ["Ng", "Vance"]


def test_active_members_plus_one_last_faculty_is_everyone_else():
    wg = _board()
    Role = WorkgroupMembership.Role
    _add(wg, "guest@x.test", Role.PLUS_ONE, "Zeta")
    _add(wg, "fac@x.test", Role.FACULTY, "Mensah")
    _add(wg, "chair@x.test", Role.CHAIR, "Roth")
    _add(wg, "mem@x.test", Role.MEMBER, "Bell")
    order = [m.user.last_name for m in wg.active_members()]
    # Chair first; faculty sorts among everyone-else (Bell, Mensah); plus-one last.
    assert order == ["Roth", "Bell", "Mensah", "Zeta"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest workgroups/tests.py -k "orders_officers or same_role_alphabetical or plus_one_last" -v`
Expected: FAIL (ordering falls back to `-start_date`, so the lists don't match).

- [ ] **Step 3: Add the rank map + helper + ordered query**

In `workgroups/models.py`, add a module-level helper. Place it just after the `Participant` dataclass (after line 92, before `class Workgroup`):

```python
def roster_rank(role) -> int:
    """Precedence rank for a roster role — lower sorts first. Officers are
    ranked explicitly; everyone else (member, faculty, web_coordinator, any
    future role) shares ROSTER_DEFAULT_RANK; plus-one guests sort last.
    See WorkgroupMembership.ROLE_RANK."""
    return WorkgroupMembership.ROLE_RANK.get(role, WorkgroupMembership.ROSTER_DEFAULT_RANK)
```

In `WorkgroupMembership`, immediately after the `LEAD_ROLES = (...)` line (~834), add:

```python
    #: Roster precedence (task #417). Leaders first in this fixed order, then
    #: everyone else at ROSTER_DEFAULT_RANK (alphabetical by last name), then
    #: plus-one guests last. President / Vice-President are the chair / co_chair
    #: rows relabeled for display (content.views.OFFICER_TITLES); rank the
    #: stored roles. MEMBER / FACULTY / WEB_COORDINATOR are intentionally NOT
    #: distinct officer positions — they take the default rank.
    ROSTER_DEFAULT_RANK = 50
    ROLE_RANK = {
        Role.CHAIR: 1,
        Role.CO_CHAIR: 2,
        Role.SECRETARY: 3,
        Role.TREASURER: 4,
        Role.ORGANIZER: 5,
        Role.REFERRAL_COORDINATOR: 6,
        Role.APPLICATIONS_COORDINATOR: 7,
        Role.ADMIN_ASSISTANT: 8,
        Role.PLUS_ONE: 99,
    }
```

Rewrite `Workgroup.active_members()` (keep the docstring; replace the return):

```python
    def active_members(self):
        """Stored ``WorkgroupMembership`` rows (hand-managed roster). For the
        full roster including derived seminar registrants, use
        :meth:`participants`.

        Ordered leaders-first by role precedence
        (:attr:`WorkgroupMembership.ROLE_RANK`), then alphabetically by last
        then first name (task #417).

        Personas (training-sandbox accounts) are excluded: they keep their
        memberships for impersonation fidelity but must never appear on a
        roster — the same rule :meth:`participants` applies at the tail. Without
        this, a seeded "Persona Board Chair" leaked onto the public Board card.
        """
        whens = [
            models.When(role=role, then=models.Value(rank))
            for role, rank in WorkgroupMembership.ROLE_RANK.items()
        ]
        return (
            self.memberships.serving()
            .exclude(user__profile__is_persona=True)
            .select_related("user", "user__profile")
            .annotate(
                _role_rank=models.Case(
                    *whens,
                    default=models.Value(WorkgroupMembership.ROSTER_DEFAULT_RANK),
                    output_field=models.IntegerField(),
                )
            )
            .order_by("_role_rank", "user__last_name", "user__first_name")
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest workgroups/tests.py -k "orders_officers or same_role_alphabetical or plus_one_last" -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the surrounding suite + lint**

Run: `uv run pytest workgroups/tests.py -q && uv run ruff check workgroups/models.py workgroups/tests.py`
Expected: all pass, no lint errors. (Existing roster tests still green — ordering doesn't change membership sets.)

- [ ] **Step 6: Commit**

```bash
git add workgroups/models.py workgroups/tests.py
git commit -m "feat(workgroups): order active_members leaders-first then alphabetical (task #417)"
```

---

### Task 2: Sort `participants()` with the shared key

**Files:**
- Modify: `workgroups/models.py` — `Workgroup.participants()` (lines 350-394): sort the assembled list before returning.
- Test: `workgroups/tests.py` (append).

**Interfaces:**
- Consumes: `roster_rank(role)` and the ordered `active_members()` from Task 1; `Participant` dataclass (`.user`, `.role`).
- Produces: `Workgroup.participants()` returns a list ordered by `(roster_rank(role), last_name, first_name)`, personas excluded.

- [ ] **Step 1: Write the failing test**

Append to `workgroups/tests.py`:

```python
def test_participants_ordered_officers_then_alphabetical():
    wg = _board()
    Role = WorkgroupMembership.Role
    _add(wg, "m2@x.test", Role.MEMBER, "Young")
    _add(wg, "chair@x.test", Role.CHAIR, "Zimmer")
    _add(wg, "m1@x.test", Role.MEMBER, "Adams")
    _add(wg, "sec@x.test", Role.SECRETARY, "Baker")
    order = [p.user.last_name for p in wg.participants()]
    assert order == ["Zimmer", "Baker", "Adams", "Young"]
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `uv run pytest workgroups/tests.py -k participants_ordered -v`
Expected: This committee has only stored members, so it *may already pass* via Task 1's ordered `active_members()` seeding the dict in order. Run it to confirm; if it passes, still add the explicit sort in Step 3 so derived-member groups (registrants appended after stored members) are also ordered. The sort is the guarantee, not the incidental dict order.

- [ ] **Step 3: Add the explicit sort**

In `workgroups/models.py`, change the end of `participants()` (the final `return [...]`) to build the filtered list, sort it, and return:

```python
        # Personas are test accounts — keep them off every roster (they retain
        # their memberships for impersonation fidelity, just not shown here).
        roster = [
            p for p in seen.values()
            if not getattr(getattr(p.user, "profile", None), "is_persona", False)
        ]
        # Leaders first by role precedence, then alphabetical by last/first name
        # (task #417). Derived members (registrants) carry MEMBER, so they land
        # in the everyone-else tier and interleave alphabetically here rather
        # than being appended after the stored rows.
        roster.sort(
            key=lambda p: (
                roster_rank(p.role),
                (p.user.last_name or "").lower(),
                (p.user.first_name or "").lower(),
            )
        )
        return roster
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest workgroups/tests.py -k participants_ordered -v`
Expected: PASS.

- [ ] **Step 5: Run the full workgroups suite + models-touching apps + lint**

Run: `uv run pytest workgroups/ committees/ content/ -q && uv run ruff check workgroups/models.py workgroups/tests.py`
Expected: all pass, no lint errors.

- [ ] **Step 6: Commit**

```bash
git add workgroups/models.py workgroups/tests.py
git commit -m "feat(workgroups): order participants() roster leaders-first (task #417)"
```

---

### Task 3: Verify the About page and a committee page end-to-end

**Files:**
- No code changes expected. This task confirms the inherited surfaces render in the new order.

**Interfaces:**
- Consumes: ordered `active_members()` / `participants()` from Tasks 1-2.

- [ ] **Step 1: Confirm the About-page roster path uses the ordered query**

Read `content/views.py` `_roster_members` (~lines 28-38) and confirm it calls `committee.active_members()` (which delegates to `workgroup.active_members()`) with no re-sort that would override ordering. If it re-sorts, note it; otherwise no change.

- [ ] **Step 2: Drive the pages in a shell**

Run:
```bash
uv run python manage.py shell -c "from committees.models import Committee; c=Committee.objects.filter(public=True).first(); print(c and [(m.get_role_display(), m.user.last_name) for m in c.active_members()])"
```
Expected: prints a roster with officer roles first (Chair/Co-chair/Secretary/Treasurer) then members alphabetical — no traceback. (If the local DB has no committees, this prints `None`/`[]`; that's acceptable — the unit tests are the authority.)

- [ ] **Step 3: Full suite + lint gate**

Run: `uv run pytest -q && uv run ruff check .`
Expected: entire suite green, lint clean.

- [ ] **Step 4: Commit (only if Step 1 required a change; otherwise skip)**

```bash
git add -A
git commit -m "chore: verify roster ordering surfaces (task #417)"
```

---

## Self-Review

**Spec coverage:**
- Rank table → Task 1 (`ROLE_RANK` + `ROSTER_DEFAULT_RANK`). ✓
- Order `active_members()` → Task 1. ✓
- Sort `participants()` → Task 2. ✓
- About page / committee / workgroup surfaces inherit → Task 3 verification. ✓
- Tests (scrambled order, same-role alphabetical, plus-one last, faculty everyone-else, participants with derived) → Tasks 1-2. ✓ (Derived-member interleaving is covered structurally by the sort; the stored-only participants test guards the common committee case.)
- No migration / no `OFFICER_TITLES` or `LEAD_ROLES` change → honored (Global Constraints). ✓

**Placeholder scan:** No TBD/TODO; all code shown in full. ✓

**Type consistency:** `roster_rank(role)` defined in Task 1, reused verbatim in Task 2. `ROLE_RANK` / `ROSTER_DEFAULT_RANK` names consistent across tasks and the `active_members()` annotation. Annotation alias `_role_rank` used only inside `active_members()`. ✓
