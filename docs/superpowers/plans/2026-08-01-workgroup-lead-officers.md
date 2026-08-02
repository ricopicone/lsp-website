# School Officers Count as Workgroup Leads — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the President / Vice-President count as leads of the Board and the
Meeting of Analysts, so the Meeting's video room is moderatable and recordable.

**Architecture:** One new predicate, `workgroups.permissions.is_workgroup_lead`,
knows about both stored `LEAD_ROLES` memberships and school officers derived from
synced `StaffRole` holders. Five call sites that today re-run the raw roster query
adopt it. Scope is deliberately two named committees, held in a module constant.

**Tech Stack:** Django 5.2, pytest-django, uv.

Spec: `docs/superpowers/specs/2026-08-01-workgroup-lead-officers-design.md`.

## Global Constraints

- Scope is exactly `OFFICER_LED_COMMITTEE_SLUGS = ("board", "meeting-of-analysts")`.
  Not the Programming Committee, not any other committee, not cartels, seminars,
  reading groups or working groups.
- `Workgroup.lead_members()` and `Workgroup._would_orphan()` must **not** adopt the
  new predicate — they guard roster mutation and the Board's stored Chair is the
  source of truth that syncs the President `StaffRole`.
- No superuser bypass inside `is_workgroup_lead`. `core.access.has_staff_role` is
  explicit-holders-only; existing separate `is_staff` clauses stay where they are.
- No model changes, no migration, no data migration, no feature flag.
- Run `uv run pytest` and `uv run ruff check .` before each commit.
- Commit messages end with the `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`
  trailer.

## File Structure

| File | Responsibility |
|---|---|
| `workgroups/permissions.py` | **Modify.** Add `OFFICER_LED_COMMITTEE_SLUGS`, `officer_lead_titles()`, `is_workgroup_lead()`; make `workgroup_has_leads()` derived-aware. |
| `workgroups/models.py` | **Modify.** `participants()` uses the helper and upgrades rather than overwrites. |
| `workgroups/membership.py` | **Modify.** `my_groups()` gets the same upgrade. |
| `video/services.py` | **Modify.** `is_owner()` adopts the predicate. |
| `video/models.py` | **Modify.** `Recording._can_host()` adopts the predicate. |
| `parletre/permissions.py` | **Modify.** `_workgroup_lead()` and the legacy committee branch of `channel_can_moderate()` adopt the predicate. |
| `workgroups/test_officer_leads.py` | **Create.** The predicate's own tests plus the decision-register consequence. |
| `video/tests/test_officer_owner.py` | **Create.** Room owner + recording host for the Meeting of Analysts. |
| `parletre/test_workgroup_channels.py` | **Modify.** Officer moderation of the Meeting's channel and the legacy committee path. |
| `workgroups/tests.py` | **Modify.** Board roster keeps its stored membership through the upgrade. |

---

### Task 1: The predicate

**Files:**
- Modify: `workgroups/permissions.py`
- Create: `workgroups/test_officer_leads.py`

**Interfaces:**
- Consumes: `core.models.StaffRole` (`PRESIDENT`, `VICE_PRESIDENT`, `holders`),
  `committees.models.Committee` (reverse one-to-one `Workgroup.committee`),
  `workgroups.models.WorkgroupMembership.LEAD_ROLES`.
- Produces:
  - `OFFICER_LED_COMMITTEE_SLUGS: tuple[str, ...]`
  - `officer_lead_titles(workgroup) -> dict[int, str]` — `{user_id: "President" | "Vice President"}`
  - `is_workgroup_lead(user, workgroup) -> bool`

- [ ] **Step 1: Write the failing tests**

Create `workgroups/test_officer_leads.py`:

```python
"""Task #480 — the school officers lead the Board and the Meeting of Analysts.

The President / Vice-President hold no ``WorkgroupMembership`` on the Meeting of
Analysts: its leadership is derived from ``StaffRole`` holders synced off the
Board roster (task #428). These tests pin the predicate that teaches the
permission layer about that derivation, and pin its deliberate narrowness.
"""

from __future__ import annotations

import datetime

import pytest

from accounts.models import Profile, User
from committees.models import Committee
from core.models import StaffRole
from workgroups.models import Workgroup, WorkgroupMembership
from workgroups.permissions import is_workgroup_lead, officer_lead_titles

pytestmark = pytest.mark.django_db


def _user(email, role=Profile.Role.ANALYST):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


def _president(email="pres@x.test"):
    u = _user(email)
    StaffRole.objects.get(key=StaffRole.PRESIDENT).holders.add(u)
    return u


def _vice_president(email="vp@x.test"):
    u = _user(email)
    StaffRole.objects.get(key=StaffRole.VICE_PRESIDENT).holders.add(u)
    return u


def _moa():
    return Committee.objects.get(slug="meeting-of-analysts").workgroup


def _board():
    return Committee.objects.get(slug="board").workgroup


def test_officer_leads_the_meeting_of_analysts():
    assert is_workgroup_lead(_president(), _moa()) is True
    assert is_workgroup_lead(_vice_president(), _moa()) is True


def test_officer_leads_the_board():
    assert is_workgroup_lead(_president(), _board()) is True


def test_officer_does_not_lead_other_groups():
    """The narrowness is the decision (spec decision 1), so it is pinned."""
    pres = _president()
    cartel = Workgroup.objects.create(kind=Workgroup.Kind.CARTEL, name="Cartel X")
    seminar = Workgroup.objects.create(kind=Workgroup.Kind.SEMINAR, name="Seminar X")
    pc = Committee.objects.get(slug="programming-committee").workgroup
    assert is_workgroup_lead(pres, cartel) is False
    assert is_workgroup_lead(pres, seminar) is False
    assert is_workgroup_lead(pres, pc) is False


def test_plain_analyst_does_not_lead_the_meeting():
    assert is_workgroup_lead(_user("plain@x.test"), _moa()) is False


def test_stored_lead_role_still_leads():
    cartel = Workgroup.objects.create(kind=Workgroup.Kind.CARTEL, name="Cartel Y")
    chair = _user("chair@x.test")
    WorkgroupMembership.objects.create(
        workgroup=cartel, user=chair, role=WorkgroupMembership.Role.CHAIR,
        start_date=datetime.date(2000, 1, 1),
    )
    assert is_workgroup_lead(chair, cartel) is True


def test_anonymous_never_leads():
    from django.contrib.auth.models import AnonymousUser
    assert is_workgroup_lead(AnonymousUser(), _moa()) is False


def test_officer_lead_titles_maps_users_to_titles():
    pres, vp = _president(), _vice_president()
    titles = officer_lead_titles(_moa())
    assert titles == {pres.pk: "President", vp.pk: "Vice President"}


def test_officer_lead_titles_empty_without_committee():
    cartel = Workgroup.objects.create(kind=Workgroup.Kind.CARTEL, name="Cartel Z")
    assert officer_lead_titles(cartel) == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest workgroups/test_officer_leads.py -q`
Expected: collection error — `ImportError: cannot import name 'is_workgroup_lead'`.

- [ ] **Step 3: Implement the predicate**

In `workgroups/permissions.py`, add below the imports:

```python
#: The bodies whose leadership the school officers hold ex officio. The
#: President / Vice-President govern the school's two standing bodies; that is a
#: governance fact about two named committees, not a per-committee setting, so it
#: lives here rather than as a field anyone could flip in the admin. Deliberately
#: narrower than ``can_manage_workgroup``, which grants the officers *management*
#: of every workgroup: fixing a cartel's roster is not leading the cartel.
OFFICER_LED_COMMITTEE_SLUGS = ("board", "meeting-of-analysts")


def officer_lead_titles(workgroup) -> dict:
    """``{user_id: "President" | "Vice President"}`` for the school officers who
    lead ``workgroup`` ex officio — ``{}`` for anything outside
    :data:`OFFICER_LED_COMMITTEE_SLUGS`.

    The Meeting of Analysts' leadership is *derived*: the officers hold no
    ``WorkgroupMembership`` there, only the ``StaffRole`` synced off the Board
    roster (task #428). This is the one place that derivation is spelled out, so
    display and permission cannot drift."""
    from django.core.exceptions import ObjectDoesNotExist

    try:
        slug = workgroup.committee.slug
    except ObjectDoesNotExist:
        return {}
    if slug not in OFFICER_LED_COMMITTEE_SLUGS:
        return {}
    from core.models import StaffRole

    titles = {}
    for key, title in (
        (StaffRole.PRESIDENT, "President"),
        (StaffRole.VICE_PRESIDENT, "Vice President"),
    ):
        role = StaffRole.objects.filter(key=key).first()
        if role is None:
            continue
        for user in role.holders.all():
            titles[user.pk] = title
    return titles


def is_workgroup_lead(user, workgroup) -> bool:
    """Whether ``user`` leads ``workgroup``: a serving lead-role membership
    (chair / co-chair / faculty / organizer), or a school officer of a body the
    officers lead ex officio.

    The single "is this person a lead" primitive. Use it instead of querying
    ``memberships.serving().filter(role__in=LEAD_ROLES)`` at a call site — that
    query cannot see derived officers, which is how the Meeting of Analysts'
    video room ended up with no moderator (task #480).

    No superuser bypass: this answers who *leads* the group, not who may act.
    Call sites that grant staff their own access keep their own clause."""
    if not getattr(user, "is_authenticated", False):
        return False
    if workgroup.memberships.serving().filter(
        user=user, role__in=WorkgroupMembership.LEAD_ROLES,
    ).exists():
        return True
    return user.pk in officer_lead_titles(workgroup)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest workgroups/test_officer_leads.py -q`
Expected: 8 passed.

If `test_officer_does_not_lead_other_groups` errors on
`Committee.objects.get(slug="programming-committee")`, check the seeded slug with
`uv run python -c "import django,os;os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.development');django.setup();from committees.models import Committee;print(list(Committee.objects.values_list('slug',flat=True)))"`
and use the real slug — do not delete the assertion.

- [ ] **Step 5: Commit**

```bash
git add workgroups/permissions.py workgroups/test_officer_leads.py
git commit -m "feat(workgroups): one lead predicate that knows the school officers (task #480)"
```

---

### Task 2: `workgroup_has_leads` becomes derived-aware

**Files:**
- Modify: `workgroups/permissions.py:45-52`
- Modify: `workgroups/test_officer_leads.py`

**Interfaces:**
- Consumes: `officer_lead_titles` from Task 1.
- Produces: no new names — `workgroup_has_leads(workgroup) -> bool` changes meaning
  for the Meeting of Analysts only.

- [ ] **Step 1: Write the failing tests**

Append to `workgroups/test_officer_leads.py`:

```python
# ---- Consequence: the Meeting of Analysts is a led group ----------------

def test_meeting_of_analysts_is_led_when_an_officer_serves():
    from workgroups.permissions import workgroup_has_leads
    _president()
    assert workgroup_has_leads(_moa()) is True


def test_meeting_decision_register_narrows_to_officers():
    """A led group's register is for its leads; a plain analyst no longer
    records the Meeting's decisions (spec decision 2)."""
    from workgroups.permissions import can_register_decision
    pres = _president()
    plain = _user("plain2@x.test")
    moa = _moa()
    assert can_register_decision(pres, moa) is True
    assert can_register_decision(plain, moa) is False


def test_cartel_stays_leaderless():
    """The regression guard for the scoping: no cartel becomes lead-led, so
    ordinary cartel members keep their decision register."""
    from workgroups.permissions import can_register_decision, workgroup_has_leads
    _president()
    cartel = Workgroup.objects.create(
        kind=Workgroup.Kind.CARTEL, name="Cartel W", has_decisions=True
    )
    member = _user("cm@x.test")
    WorkgroupMembership.objects.create(
        workgroup=cartel, user=member, start_date=datetime.date(2000, 1, 1)
    )
    assert workgroup_has_leads(cartel) is False
    assert can_register_decision(member, cartel) is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest workgroups/test_officer_leads.py -q -k "led or register or leaderless"`
Expected: `test_meeting_of_analysts_is_led_when_an_officer_serves` and
`test_meeting_decision_register_narrows_to_officers` FAIL (assert False is True /
True is False). `test_cartel_stays_leaderless` already passes — it is the guard.

- [ ] **Step 3: Implement**

Replace `workgroup_has_leads` in `workgroups/permissions.py`:

```python
def workgroup_has_leads(workgroup) -> bool:
    """Whether the group is led at all — a serving lead-role member (chair,
    co-chair, faculty, organizer), or a school officer leading it ex officio.
    False for leaderless groups like cartels (a plus-one is deliberately not a
    lead), which is what lets any of their members record a decision."""
    if workgroup.memberships.serving().filter(
        role__in=WorkgroupMembership.LEAD_ROLES
    ).exists():
        return True
    return bool(officer_lead_titles(workgroup))
```

Leave `Workgroup.lead_members()` and `Workgroup._would_orphan()` in
`workgroups/models.py` untouched — see Global Constraints.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest workgroups/test_officer_leads.py workgroups/tests.py -q`
Expected: all pass, including the pre-existing
`test_decision_leaderless_any_member_can_register` and
`test_decision_leaderled_only_leads_register`.

- [ ] **Step 5: Commit**

```bash
git add workgroups/permissions.py workgroups/test_officer_leads.py
git commit -m "feat(workgroups): the Meeting of Analysts is a led group (task #480)"
```

---

### Task 3: Video — room owner and recording host

**Files:**
- Modify: `video/services.py:350-366`
- Modify: `video/models.py:155-168`
- Create: `video/tests/test_officer_owner.py`

**Interfaces:**
- Consumes: `is_workgroup_lead` from Task 1.
- Produces: no new names. `services.is_owner(workgroup, user)` and
  `Recording._can_host(user)` gain the derived officers.

- [ ] **Step 1: Write the failing tests**

Create `video/tests/test_officer_owner.py`:

```python
"""Task #480 — the school officers moderate and record the Meeting's room.

Before this, opening the Meeting of Analysts' video room gave *nobody*
moderator controls and *nobody* a Record button: its leaders are derived
StaffRole holders, and ``is_owner`` only saw stored memberships.
"""

from __future__ import annotations

import pytest

from accounts.models import Profile, User
from committees.models import Committee
from core.models import StaffRole
from video import services
from video.models import DailyRoom, Recording
from workgroups.models import Workgroup

pytestmark = pytest.mark.django_db


def _analyst(email):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    return u


def _president(email="pres@x.test"):
    u = _analyst(email)
    StaffRole.objects.get(key=StaffRole.PRESIDENT).holders.add(u)
    return u


def _moa():
    return Committee.objects.get(slug="meeting-of-analysts").workgroup


def test_president_is_owner_of_the_meetings_room():
    assert services.is_owner(_moa(), _president()) is True


def test_plain_analyst_is_not_owner_of_the_meetings_room():
    assert services.is_owner(_moa(), _analyst("plain@x.test")) is False


def test_president_is_not_owner_of_a_cartel_room():
    cartel = Workgroup.objects.create(kind=Workgroup.Kind.CARTEL, name="Cartel V")
    assert services.is_owner(cartel, _president()) is False


def test_president_hosts_a_recording_from_the_meetings_room():
    room = DailyRoom.objects.create(
        workgroup=_moa(), name="lsp-moa", url="https://lsp.daily.co/lsp-moa"
    )
    rec = Recording.objects.create(room=room, daily_recording_id="r1")
    assert rec._can_host(_president()) is True
    assert rec._can_host(_analyst("plain2@x.test")) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest video/tests/test_officer_owner.py -q`
Expected: `test_president_is_owner_of_the_meetings_room` and
`test_president_hosts_a_recording_from_the_meetings_room` FAIL
(`assert False is True`). The two negative tests pass already.

- [ ] **Step 3: Implement**

In `video/services.py`, replace the tail of `is_owner`:

```python
    from workgroups.permissions import is_workgroup_lead

    return is_workgroup_lead(user, owner)
```

(deleting the `from workgroups.models import WorkgroupMembership` import and the
`owner.memberships.serving().filter(...)` query it fed).

In `video/models.py`, replace the body of `Recording._can_host` after the
`wg is None` guard:

```python
        from workgroups.permissions import is_workgroup_lead

        return getattr(user, "is_staff", False) or is_workgroup_lead(user, wg)
```

(deleting the `from workgroups.models import WorkgroupMembership` import above it).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest video/tests/ -q`
Expected: all pass — the new file plus the existing event-room, channel-room and
recording suites.

- [ ] **Step 5: Commit**

```bash
git add video/services.py video/models.py video/tests/test_officer_owner.py
git commit -m "feat(video): the school officers moderate and record their bodies' rooms (task #480)"
```

---

### Task 4: Parlêtre channel moderation

**Files:**
- Modify: `parletre/permissions.py:99-106` and `:134-142`
- Modify: `parletre/test_workgroup_channels.py`

**Interfaces:**
- Consumes: `is_workgroup_lead` from Task 1.
- Produces: no new names.

- [ ] **Step 1: Write the failing tests**

Append to `parletre/test_workgroup_channels.py`:

```python
# ---- Task #480: derived school officers moderate their bodies' channels ----

def _president_user(email="pres@x.test"):
    from core.models import StaffRole
    u = _user(email)
    StaffRole.objects.get(key=StaffRole.PRESIDENT).holders.add(u)
    return u


def test_president_moderates_the_meetings_workgroup_channel():
    from committees.models import Committee
    wg = Committee.objects.get(slug="meeting-of-analysts").workgroup
    channel = wg.channels.get(kind=Channel.Kind.FORUM)
    assert channel_can_moderate(channel, _president_user()) is True
    assert channel_can_moderate(channel, _user("plain@x.test")) is False


def test_president_moderates_a_legacy_committee_access_channel():
    """The committee-keyed branch resolves only for committees — which is
    exactly the Board and the Meeting — so it must see derived officers too."""
    from committees.models import Committee
    board = Committee.objects.get(slug="board")
    channel = Channel.objects.create(
        name="Board room", slug="board-room", kind=Channel.Kind.FORUM,
        access=Channel.Access.COMMITTEE, committee=board,
    )
    assert channel_can_moderate(channel, _president_user()) is True


def test_president_does_not_moderate_a_cartel_channel():
    wg = _wg(name="Cartel P")
    channel = wg.channels.get(kind=Channel.Kind.FORUM)
    assert channel_can_moderate(channel, _president_user()) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest parletre/test_workgroup_channels.py -q -k president`
Expected: the first two FAIL (`assert False is True`); the cartel one passes.

If `Channel.Access.COMMITTEE` does not exist under that name, read the `Access`
choices in `parletre/models.py` and use the real member — the legacy branch is
gated on `channel.committee_id`, so the access value only has to be the one that
routes past the `PRIVATE` and `WORKGROUP` branches without `user.is_staff`.

- [ ] **Step 3: Implement**

In `parletre/permissions.py`, replace `_workgroup_lead`:

```python
def _workgroup_lead(workgroup, user) -> bool:
    """Whether ``user`` leads ``workgroup`` — the role that moderates its
    channel. Includes the school officers who lead the Board and the Meeting of
    Analysts ex officio (task #480)."""
    from workgroups.permissions import is_workgroup_lead

    return is_workgroup_lead(user, workgroup)
```

And in `channel_can_moderate`, replace the legacy committee branch:

```python
    # Legacy committee-access channels: the gating committee's leads moderate,
    # read via its workgroup (which is where derived school officers live).
    if channel.committee_id is not None:
        from committees.models import Committee
        from workgroups.permissions import is_workgroup_lead

        committee = (
            Committee.objects.filter(pk=channel.committee_id)
            .select_related("workgroup")
            .first()
        )
        wg = committee.workgroup if committee else None
        return bool(wg and is_workgroup_lead(user, wg))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest parletre/ -q`
Expected: all pass, including the existing no-staff-bypass tests.

- [ ] **Step 5: Commit**

```bash
git add parletre/permissions.py parletre/test_workgroup_channels.py
git commit -m "feat(parletre): the school officers moderate their bodies' channels (task #480)"
```

---

### Task 5: Roster display uses the same helper

**Files:**
- Modify: `workgroups/models.py:443-522` (`participants`)
- Modify: `workgroups/membership.py:188-222` (`my_groups`)
- Modify: `workgroups/tests.py`

**Interfaces:**
- Consumes: `officer_lead_titles` from Task 1.
- Produces: no new names. `Participant.officer_title` and `MyGroup.is_lead` /
  `MyGroup.role_label` gain derived officers; a stored membership survives.

- [ ] **Step 1: Write the failing tests**

Append to `workgroups/tests.py`:

```python
def test_board_officer_roster_row_keeps_its_stored_membership():
    """Task #480: participants() upgrades an officer's entry rather than
    replacing it — the old MoA-only block overwrote the Participant outright,
    which on the Board would have discarded the Chair's stored row."""
    from core.models import StaffRole

    board = Committee.objects.get(slug="board")
    wg = board.workgroup
    chair = _user("chair-b@x.test", role=Profile.Role.ANALYST)
    WorkgroupMembership.objects.create(
        workgroup=wg, user=chair, role=WorkgroupMembership.Role.CHAIR,
        start_date=datetime.date(2026, 1, 1),
    )
    StaffRole.objects.get(key=StaffRole.PRESIDENT).holders.add(chair)

    row = {p.user.email: p for p in wg.participants()}["chair-b@x.test"]
    assert row.membership is not None          # stored row survived
    assert row.is_lead is True
    assert row.role_label == "President"


def test_my_groups_shows_the_officer_as_a_lead_of_the_meeting():
    from core.models import StaffRole
    from workgroups.membership import my_groups

    pres = _user("pres-mg@x.test", role=Profile.Role.ANALYST)
    StaffRole.objects.get(key=StaffRole.PRESIDENT).holders.add(pres)
    moa = Committee.objects.get(slug="meeting-of-analysts").workgroup

    row = {r.workgroup.id: r for r in my_groups(pres)}[moa.id]
    assert row.is_lead is True
    assert row.role_label == "President"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest workgroups/tests.py -q -k "stored_membership or my_groups_shows"`
Expected: `test_board_officer_roster_row_keeps_its_stored_membership` FAILS on
`row.membership is not None` only if the MoA block is widened naively — with the
block still MoA-only it passes, and it is the guard for Step 3.
`test_my_groups_shows_the_officer_as_a_lead_of_the_meeting` FAILS
(`role_label == "Member"`).

- [ ] **Step 3: Implement**

In `workgroups/models.py::participants`, delete the inline
`is_moa` / `officer_rows` block (lines ~463-489) and put this after the
auto-member loop and before the derived-events loop:

```python
        # The Board's and the Meeting of Analysts' leaders are the school
        # officers, synced from the Board roster (task #428) rather than stored
        # as lead-role memberships. Upgrade their entry — a stored Chair keeps
        # their membership and merely gains the title — reusing Chair/Co-chair
        # role values so they rank first (task #480).
        from .permissions import officer_lead_titles

        officer_role = {
            "President": WorkgroupMembership.Role.CHAIR,
            "Vice President": WorkgroupMembership.Role.CO_CHAIR,
        }
        for user_id, title in officer_lead_titles(self).items():
            existing = seen.get(user_id)
            if existing is not None:
                existing.is_lead = True
                existing.officer_title = title
                if existing.membership is None:
                    existing.role = officer_role[title]
                continue
            user = User.objects.filter(pk=user_id).select_related("profile").first()
            if user is not None:
                seen[user_id] = Participant(
                    user=user, role=officer_role[title], is_lead=True,
                    officer_title=title,
                )
```

`Participant` is a dataclass, so attribute assignment works; confirm it is not
declared `frozen=True` and if it is, rebuild the entry with
`dataclasses.replace(existing, is_lead=True, officer_title=title)`.

Add `from accounts.models import User` at the top of the method if `User` is not
already importable in that module scope — check first; `workgroups/models.py`
may import it lazily elsewhere.

In `workgroups/membership.py::my_groups`, after the `role_label` / `is_lead`
branches and before `rows.append(...)`:

```python
        officer_title = officer_lead_titles(wg).get(user.pk)
        if officer_title:
            role_label = officer_title
            is_lead = True
```

with `from workgroups.permissions import officer_lead_titles` imported at the top
of the function (module-level would risk an import cycle — `permissions` imports
`models`).

Note the candidate set: an officer reaches `my_groups` for the Meeting via the
role-derived branch (they are an analyst), and for the Board via their stored
row. No new candidate discovery is needed.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest workgroups/ -q`
Expected: all pass, including the pre-existing
`test_moa_roster_shows_president_and_vp_as_leaders`.

- [ ] **Step 5: Full suite and lint**

Run: `uv run pytest -q` then `uv run ruff check .`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add workgroups/models.py workgroups/membership.py workgroups/tests.py
git commit -m "refactor(workgroups): roster display shares the officer-lead helper (task #480)"
```

---

### Task 6: Documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the status entry**

Append a bullet to the "Done" list in `CLAUDE.md`, in the house style of the
neighbouring task entries (what was wrong, why, what changed, what was
deliberately not changed): the derived-officer gap, the five call sites, the
Board+MoA scoping, the orphan guard held back, and the Meeting's decision
register narrowing.

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record the officer-lead predicate (task #480)"
```

---

## Verification on prod (after deploy)

Not a task — run it once the deploy goes green. Over SSM (see the `ssm-prod-exec`
memory; the active service alternates `web_blue` / `web_green`):

```python
from workgroups.models import Workgroup
from video.services import is_owner
for wg in Workgroup.objects.all():
    people = list(wg.participants())
    if people and not any(is_owner(wg, p.user) for p in people):
        print(wg.name, wg.kind, len(people))
```

Pass `.user`, not the participant, or `is_owner` raises
`ValueError: Must be "User" instance`.

**`participants()`, not `active_members()`.** The ticket's recipe used
`active_members()`, which returns stored membership rows only — on the Meeting of
Analysts that is just the Applications Coordinator, so the derived officers this
task is about are invisible to it and the audit reports the Meeting as still
broken after a working fix. Confirmed on prod 2026-08-01.

Expected output: `Working Group on Cartels` only. Its fix is data — appoint an
organizer in the group's Settings roster — and is out of scope for this plan.
