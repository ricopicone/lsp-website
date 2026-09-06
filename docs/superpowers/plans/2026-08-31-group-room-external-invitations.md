# Group Room External Invitations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the leaders of a group invite someone from outside it into that group's meeting room, by name or by secret link, without putting them on the roster.

**Architecture:** `RoomInvitation` becomes polymorphic over three targets (`personal_room` / `workgroup` / `event`) with an exactly-one check constraint, mirroring `DailyRoom`'s owner style. Everything that differs between targets is answered by one adapter in a new `video/invitations.py`; the rest of the code asks the adapter rather than branching. A non-member entrant is admitted only while someone is already in the room ("a guest is never the first one in the room"), checked at token mint and rendered as a polling doorstep otherwise.

**Tech Stack:** Django 5.2, pytest-django, DaisyUI/Tailwind templates, Daily.co REST (stubbed in tests).

**Spec:** `docs/superpowers/specs/2026-08-31-group-room-external-invitations-design.md`

## Global Constraints

- Parlêtre channel video rooms are **out of scope**; do not add a `channel` target.
- Who may invite: `video.services.is_owner(owner, user)` for group targets; the room's own member for a personal target.
- A group invitation of **either kind** has `expires_at = None`. A personal guest link keeps `DEFAULT_TTL_DAYS = 30`.
- Presence is `services.room_participant_count(getattr(owner, "video_room", None)) > 0`. **Never** call `ensure_room` from a presence or doorstep path.
- The guest route `/meet/g/<token>/` and the URL name `video:guest_room` must not change: links have been mailed.
- GET on the guest doorstep mints nothing (no Daily call).
- A guest is never `is_owner`.
- Member-facing copy uses commas, not em dashes (`em-dash-prose-style`).
- Tailwind classes must appear in a template, never only in Python (`tailwind-classes-set-in-python`).
- Every POST form is already submit-once guarded globally; do not add per-form guards.
- Run `uv run pytest` and `uv run ruff check .` before each commit.

---

### Task 1: `RoomInvitation` gains its target

**Files:**
- Modify: `video/models.py` (the `RoomInvitation` class, ~line 470 onwards)
- Modify: `video/services_personal.py` (`guest_invitation` select_related)
- Modify: `video/forms_personal.py` (`build`)
- Modify: `video/views_personal.py` (`room_invite_revoke` lookup)
- Modify: `video/notifications_personal.py` (`invitation.room` reads)
- Modify: `video/admin.py` (if it lists `room`)
- Create: `video/migrations/0008_roominvitation_targets.py` (generated)
- Test: `video/tests/test_invitation_targets.py`

**Interfaces:**
- Produces: `RoomInvitation.personal_room`, `.workgroup`, `.event`, `.invited_by`; `RoomInvitation.target_object` returning the set one; constraint `video_invitation_exactly_one_target`.

- [ ] **Step 1: Write the failing test**

```python
"""RoomInvitation names exactly one target (task #694)."""
from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from video.models import RoomInvitation

from .factories import seminar, user
from .test_personal_rooms import member, room_for

pytestmark = pytest.mark.django_db


def _workgroup():
    ev = seminar()
    return ev.ensure_workgroup()


def test_a_workgroup_invitation_needs_no_personal_room():
    wg = _workgroup()
    inv = RoomInvitation.objects.create(
        workgroup=wg, token=RoomInvitation.new_token(), guest_name="Jane"
    )
    assert inv.target_object == wg


def test_two_targets_are_refused():
    wg = _workgroup()
    room = room_for(member())
    with pytest.raises(IntegrityError), transaction.atomic():
        RoomInvitation.objects.create(
            workgroup=wg, personal_room=room,
            token=RoomInvitation.new_token(), guest_name="Jane",
        )


def test_no_target_is_refused():
    with pytest.raises(IntegrityError), transaction.atomic():
        RoomInvitation.objects.create(
            token=RoomInvitation.new_token(), guest_name="Jane"
        )


def test_invited_by_records_who_opened_the_door():
    wg = _workgroup()
    lead = user("lead@example.com")
    inv = RoomInvitation.objects.create(
        workgroup=wg, token=RoomInvitation.new_token(), guest_name="Jane",
        invited_by=lead,
    )
    assert inv.invited_by == lead
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest video/tests/test_invitation_targets.py -q`
Expected: FAIL — `RoomInvitation() got unexpected keyword arguments: 'workgroup'`.

- [ ] **Step 3: Change the model**

In `video/models.py`, rename the `room` field and add the three new ones. Keep `related_name="invitations"` on the personal FK so `PersonalRoom.invitations` and `live_invitations()` are untouched:

```python
    personal_room = models.ForeignKey(
        PersonalRoom, null=True, blank=True, on_delete=models.CASCADE,
        related_name="invitations",
    )
    workgroup = models.ForeignKey(
        "workgroups.Workgroup", null=True, blank=True, on_delete=models.CASCADE,
        related_name="room_invitations",
    )
    #: A one-off event that owns its own room. An *offering* event meets in its
    #: workgroup's room, so it is never the target — see
    #: ``video.invitations.target_for_event``.
    event = models.ForeignKey(
        "events.Event", null=True, blank=True, on_delete=models.CASCADE,
        related_name="room_invitations",
    )
    invited_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="issued_room_invitations",
    )
```

Add to `Meta.constraints`, beside the existing kind constraint:

```python
            models.CheckConstraint(
                condition=(
                    Q(personal_room__isnull=False, workgroup__isnull=True, event__isnull=True)
                    | Q(personal_room__isnull=True, workgroup__isnull=False, event__isnull=True)
                    | Q(personal_room__isnull=True, workgroup__isnull=True, event__isnull=False)
                ),
                name="video_invitation_exactly_one_target",
            ),
```

And a property beside `is_guest`:

```python
    @property
    def target_object(self):
        """The thing this invitation is *to* — a PersonalRoom, a Workgroup, or a
        one-off Event. ``video.invitations.target_of`` wraps it in the adapter
        that knows how each behaves."""
        return self.personal_room or self.workgroup or self.event
```

Update the class docstring to say there are three targets and that a group
invitation of either kind never expires.

- [ ] **Step 4: Fix every reader of the old field name**

`git grep -n "invitation.room\b\|\.room__user\|\"room\": self.room\|room=self.room\|room__user"` inside `video/` and `formation/`, and rename each to `personal_room`. Known sites:
- `services_personal.guest_invitation`: `select_related("room", "room__user")` → `("personal_room", "personal_room__user")`
- `views_personal.room_invite_revoke`: `room__user=request.user` → `personal_room__user=request.user`
- `forms_personal.InvitationForm.build`: `"room": self.room` → `"personal_room": self.room`
- `notifications_personal`: `invitation.room` → `invitation.personal_room`
- `video/admin.py`: any `list_display` / `raw_id_fields` naming `room`

- [ ] **Step 5: Make the migration**

Run: `uv run python manage.py makemigrations video -n roominvitation_targets`
Confirm the generated file contains a `RenameField(old_name="room", new_name="personal_room")` (answer Django's prompt with the rename if asked), three `AddField`s, `AlterField` making `personal_room` nullable, and the constraint add. Read the file before trusting it.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest video/tests/test_invitation_targets.py video/tests/test_personal_rooms.py video/tests/test_personal_views.py -q`
Expected: PASS, including every #687 regression.

- [ ] **Step 7: Commit**

```bash
git add video/models.py video/migrations video/services_personal.py video/forms_personal.py video/views_personal.py video/notifications_personal.py video/admin.py video/tests/test_invitation_targets.py
git commit -m "feat(video): a room invitation names one of three targets (task #694)"
```

---

### Task 2: The target adapter

**Files:**
- Create: `video/invitations.py`
- Test: `video/tests/test_invitation_targets.py` (append)

**Interfaces:**
- Produces: `target_for(obj)`, `target_of(invitation)`, `target_for_event(event)`, and a `Target` interface with `.owner`, `.kwargs`, `.label`, `.invitations`, `.someone_present()`, `.may_invite(user)`, `.room_url()`, `.excluded_user_ids()`, `.default_expiry()`, `.is_personal`.

- [ ] **Step 1: Write the failing test**

```python
def test_an_offering_event_targets_its_workgroup():
    from video import invitations

    ev = seminar()
    wg = ev.ensure_workgroup()
    target = invitations.target_for_event(ev)
    assert target.owner == wg


def test_a_one_off_event_targets_itself():
    from video import invitations

    from .factories import special_event

    ev = special_event()
    assert invitations.target_for_event(ev).owner == ev


def test_a_group_invitation_never_expires():
    from video import invitations

    wg = _workgroup()
    assert invitations.target_for(wg).default_expiry() is None


def test_a_personal_guest_link_still_expires_in_thirty_days():
    from video import invitations

    room = room_for(member())
    assert invitations.target_for(room).default_expiry() is not None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest video/tests/test_invitation_targets.py -q -k target`
Expected: FAIL — `No module named 'video.invitations'`.

- [ ] **Step 3: Write the adapter**

```python
"""What an invitation is *to*, and how each kind of target behaves (task #694).

Three targets — a member's ``PersonalRoom``, a ``Workgroup``, or a one-off
``Event`` that owns its own room — differ in a handful of ways: who may issue an
invitation, who has to be in the room before a guest may come in, how long a
guest link lives, and where an invited account holder goes once signed in.

Every one of those differences is answered here, so no call site branches on the
target. A fact each surface re-derives is how ``Program.public_program_year_q``
came to be written and never called (task #532).
"""
from __future__ import annotations

from django.urls import reverse

from . import services
from .models import RoomInvitation


class Target:
    """One invitable room, behind a uniform interface."""

    is_personal = False

    def __init__(self, owner):
        self.owner = owner

    # -- identity ---------------------------------------------------------
    @property
    def kwargs(self) -> dict:
        raise NotImplementedError

    @property
    def label(self) -> str:
        raise NotImplementedError

    @property
    def invitations(self):
        return RoomInvitation.objects.filter(**self.kwargs)

    def live_invitations(self):
        return self.invitations.live().select_related("invited_user", "invited_by")

    # -- policy -----------------------------------------------------------
    def may_invite(self, user) -> bool:
        return services.is_owner(self.owner, user)

    def default_expiry(self):
        """Group invitations never expire; revoking is how one ends."""
        return None

    def someone_present(self) -> bool:
        """Whether anybody is in the room right now.

        Reads the existing ``DailyRoom`` row, never ``ensure_room``: provisioning
        from a doorstep would create a room for a group that has never met, and
        would make a GET write.
        """
        return services.room_participant_count(getattr(self.owner, "video_room", None)) > 0

    def excluded_user_ids(self) -> set:
        raise NotImplementedError

    def room_url(self) -> str:
        raise NotImplementedError


class WorkgroupTarget(Target):
    @property
    def kwargs(self):
        return {"workgroup": self.owner}

    @property
    def label(self):
        return self.owner.name

    def excluded_user_ids(self):
        # participants(), not active_members(): the latter is stored rows only,
        # so a seminar's registrants and a committee's ex-officio officers would
        # be invisible (active-members-vs-participants).
        return {p.user_id for p in self.owner.participants()}

    def room_url(self):
        return reverse("video:workgroup_room", args=[self.owner.slug])


class EventTarget(Target):
    @property
    def kwargs(self):
        return {"event": self.owner}

    @property
    def label(self):
        return self.owner.title

    def excluded_user_ids(self):
        from registrations.models import Registration

        return set(
            Registration.objects.filter(
                event=self.owner,
                status__in=(Registration.Status.PAID, Registration.Status.COMPED),
            ).values_list("user_id", flat=True)
        )

    def room_url(self):
        return reverse("video:event_room", args=[self.owner.slug])


class PersonalTarget(Target):
    is_personal = True

    @property
    def kwargs(self):
        return {"personal_room": self.owner}

    @property
    def label(self):
        from . import services_personal

        return services_personal.owner_display(self.owner)

    def may_invite(self, user) -> bool:
        """The room's own member, and nobody else — not even the site-technical
        roles, who are excluded from personal rooms entirely
        (``can_enter_personal``). Unifying revoke across the three targets must
        not widen this."""
        return getattr(user, "pk", None) == self.owner.user_id

    def default_expiry(self):
        return RoomInvitation.default_expiry()

    def someone_present(self) -> bool:
        return super().someone_present()

    def excluded_user_ids(self):
        return {self.owner.user_id}

    def room_url(self):
        return reverse("video:personal_room", args=[self.owner.slug])


def target_for(owner) -> Target:
    from events.models import Event
    from workgroups.models import Workgroup

    from .models import PersonalRoom

    if isinstance(owner, Workgroup):
        return WorkgroupTarget(owner)
    if isinstance(owner, Event):
        return EventTarget(owner)
    if isinstance(owner, PersonalRoom):
        return PersonalTarget(owner)
    raise TypeError(f"{owner!r} cannot own room invitations")


def target_for_event(event, *, create: bool = False) -> Target | None:
    """The target for an event's room.

    An offering event (seminar, reading group, cartel) meets in its *workgroup's*
    room, so it is never its own target: minting ``event``-target invitations for
    one would attach them to a room the event does not own, and they would admit
    nobody.
    """
    owner = services.room_owner_for_event(event, create=create)
    return None if owner is None else target_for(owner)


def target_of(invitation) -> Target:
    return target_for(invitation.target_object)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest video/tests/test_invitation_targets.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add video/invitations.py video/tests/test_invitation_targets.py
git commit -m "feat(video): one adapter for what a room invitation targets (task #694)"
```

---

### Task 3: The entry rule

**Files:**
- Modify: `video/invitations.py`
- Modify: `video/services_personal.py` (import `EntryRefused` from `invitations`, keep the name exported)
- Test: `video/tests/test_group_invitations.py`

**Interfaces:**
- Produces: `EntryRefused(message, waiting=False)`, `invitation_for(target, user)`, `guest_invitation(token)`, `check_entry(target, user, invitation=None)`, `guest_token(daily_room, guest_name)`.

- [ ] **Step 1: Write the failing test**

```python
"""A guest is never the first one in a group's room (task #694)."""
from __future__ import annotations

import pytest

from video import invitations as inv
from video.models import RoomInvitation

from .factories import daily_on, seminar, special_event, user

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _daily_on():
    with daily_on:
        yield


@pytest.fixture
def present(monkeypatch):
    state = {"live": False}
    monkeypatch.setattr(
        "video.services.room_participant_count", lambda room: 1 if state["live"] else 0
    )
    return state


def group():
    return seminar().ensure_workgroup()


def test_an_invited_outsider_waits_for_an_empty_room(present):
    wg = group()
    guest = user("guest@example.com")
    invitation = RoomInvitation.objects.create(workgroup=wg, invited_user=guest)
    target = inv.target_for(wg)
    with pytest.raises(inv.EntryRefused) as refused:
        inv.check_entry(target, guest, invitation=invitation)
    assert refused.value.waiting is True


def test_the_same_outsider_is_admitted_once_someone_is_in_it(present):
    wg = group()
    guest = user("guest@example.com")
    invitation = RoomInvitation.objects.create(workgroup=wg, invited_user=guest)
    present["live"] = True
    inv.check_entry(inv.target_for(wg), guest, invitation=invitation)


def test_an_uninvited_stranger_is_refused_outright(present):
    present["live"] = True
    stranger = user("stranger@example.com")
    with pytest.raises(inv.EntryRefused) as refused:
        inv.check_entry(inv.target_for(group()), stranger)
    assert refused.value.waiting is False


def test_a_revoked_invitation_does_not_admit(present):
    wg = group()
    guest = user("guest@example.com")
    invitation = RoomInvitation.objects.create(workgroup=wg, invited_user=guest)
    invitation.revoke()
    present["live"] = True
    with pytest.raises(inv.EntryRefused):
        inv.check_entry(inv.target_for(wg), guest, invitation=invitation)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest video/tests/test_group_invitations.py -q`
Expected: FAIL — `module 'video.invitations' has no attribute 'EntryRefused'`.

- [ ] **Step 3: Move `EntryRefused` and add the entry rule**

Move the `EntryRefused` class verbatim from `services_personal.py` into `invitations.py` (docstring included), and in `services_personal.py` replace it with `from .invitations import EntryRefused  # noqa: F401 — re-exported`. Then add to `invitations.py`:

```python
def invitation_for(target, user):
    """``user``'s live account-bound invitation to ``target``, if any."""
    if not getattr(user, "is_authenticated", False):
        return None
    return target.invitations.live().filter(invited_user=user).first()


def guest_invitation(token: str):
    """The live guest invitation a secret URL names, or None.

    Not single-use and not consumed by looking: email link-scanners pre-click
    links on exactly the addresses this gets mailed to
    (``auth-email-scanner-and-reset-gotchas``). Revoking is how one ends early.
    """
    if not token:
        return None
    return (
        RoomInvitation.objects.live()
        .filter(token=token)
        .select_related("personal_room", "personal_room__user", "workgroup", "event")
        .first()
    )


def _admits(invitation) -> bool:
    """Re-checked rather than trusted, so a caller that fetched an invitation
    without ``live()`` cannot subvert the gate."""
    return invitation is not None and invitation.is_live


def check_entry(target, user, *, invitation=None) -> None:
    """Raise :class:`EntryRefused` unless ``user`` may join ``target`` right now.

    A personal room keeps its own stricter rule in
    ``services_personal.check_entry`` (the owner must be the one present); this
    is the group rule:

        A guest is never the first one in the room.
    """
    if target.is_personal:  # pragma: no cover — routed via services_personal
        raise TypeError("use services_personal.check_entry for a personal room")
    if services.can_enter(target.owner, user):
        return
    if not _admits(invitation) and invitation_for(target, user) is None:
        raise EntryRefused(
            "This is a private meeting room, and you have not been invited to it."
        )
    if not target.someone_present():
        raise EntryRefused(
            f"The meeting in {target.label} has not started yet.", waiting=True
        )


def guest_token(daily_room, guest_name: str, **kwargs) -> str:
    """A non-owner Daily token carrying the display name a guest typed.

    ``services.mint_token`` derives the name from a ``User`` and a guest has
    none, so this is the one place that reaches the Daily client directly.
    """
    import time

    from django.conf import settings

    from . import daily as daily_api

    exp = kwargs.pop("exp", None) or int(time.time()) + settings.DAILY_TOKEN_TTL_MINUTES * 60
    return daily_api.create_meeting_token(
        room_name=daily_room.name, user_name=guest_name[:255], is_owner=False,
        exp=exp, **kwargs,
    )
```

Then delete `_guest_token` from `services_personal.py` and have `room_context` call `invitations.guest_token(daily_room, guest_name, knocking=knocking)`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest video/tests/ -q`
Expected: PASS across the whole video suite.

- [ ] **Step 5: Commit**

```bash
git add video/invitations.py video/services_personal.py video/tests/test_group_invitations.py
git commit -m "feat(video): a guest is never the first one in a group's room (task #694)"
```

---

### Task 4: The invitation form, parameterized by target

**Files:**
- Create: `video/forms_invitations.py` (moved from `forms_personal.py`)
- Modify: `video/forms_personal.py` (keeps `PersonalRoomSettingsForm` only)
- Modify: `video/views_personal.py`, `formation/views.py` (imports)
- Test: `video/tests/test_group_invitations.py` (append)

**Interfaces:**
- Produces: `InvitationForm(data=None, *, target)`, `.already_invited(recipient)`, `.build(recipient, by=None)`, `Recipient`, `GuestJoinForm`.

- [ ] **Step 1: Write the failing test**

```python
def test_the_picker_leaves_out_people_already_on_the_roster():
    from video.forms_invitations import InvitationForm

    wg = group()
    inside = user("inside@example.com")
    outside = user("outside@example.com")
    wg.add_member(inside)
    form = InvitationForm(target=inv.target_for(wg))
    choices = set(form.fields["members"].queryset.values_list("pk", flat=True))
    assert outside.pk in choices
    assert inside.pk not in choices


def test_building_a_group_invitation_records_the_inviter_and_no_expiry():
    from video.forms_invitations import InvitationForm, Recipient

    wg = group()
    lead = user("lead@example.com")
    guest = user("guest@example.com")
    form = InvitationForm(target=inv.target_for(wg))
    invitation = form.build(Recipient(user=guest, name="", email=""), by=lead)
    assert invitation.workgroup == wg
    assert invitation.expires_at is None
    assert invitation.invited_by == lead
```

Check `Workgroup.add_member`'s real signature with `grep -n "def add_member" workgroups/models.py` and match it; if it takes a role, pass the default.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest video/tests/test_group_invitations.py -q -k "picker or building"`
Expected: FAIL — `No module named 'video.forms_invitations'`.

- [ ] **Step 3: Move and generalize the form**

`git mv`-style: copy `InvitationForm`, `Recipient`, `MemberChoiceField`, `_RECIPIENT_LINE` and `GuestJoinForm` out of `forms_personal.py` into a new `video/forms_invitations.py`, leaving `PersonalRoomSettingsForm` (and `_INPUT` / `_SELECT`, which it needs) behind. Then change three things:

- `def __init__(self, *args, target=None, **kwargs)`, storing `self.target = target`;
- `_member_queryset` excludes `self.target.excluded_user_ids()` rather than only the room's owner:

```python
        if self.target is not None:
            qs = qs.exclude(pk__in=self.target.excluded_user_ids())
```

- `already_invited` and `build` go through the target:

```python
    def already_invited(self, recipient) -> bool:
        if recipient.user is None or self.target is None:
            return False
        return self.target.invitations.live().filter(invited_user=recipient.user).exists()

    def build(self, recipient, *, by=None) -> RoomInvitation:
        """Create the invitation for one recipient (account-bound or guest)."""
        common = {
            **self.target.kwargs,
            "note": (self.cleaned_data.get("note") or "").strip(),
            "invited_by": by,
        }
        if recipient.user is not None:
            # No expiry on either kind for a group; for a personal room only the
            # account-bound kind is open-ended. It names a person who has to sign
            # in, so it is not a secret that can be forwarded.
            return RoomInvitation.objects.create(
                invited_user=recipient.user, expires_at=None, **common
            )
        return RoomInvitation.objects.create(
            token=RoomInvitation.new_token(),
            guest_name=recipient.name,
            guest_email=recipient.email,
            expires_at=self.target.default_expiry(),
            **common,
        )
```

Note `build` is called without `cleaned_data` in the test above, so guard the note: `(self.cleaned_data.get("note") if self.is_bound else "") or ""` — or simply give the form `self.cleaned_data = getattr(self, "cleaned_data", {})` at the top of `build`. Use the latter, one line, and say why in a comment.

Update the two importers: `video/views_personal.py` (`from .forms_invitations import GuestJoinForm, InvitationForm` / `from .forms_personal import PersonalRoomSettingsForm`) and `formation/views.py` (same split), and change `InvitationForm(room=room)` to `InvitationForm(target=target_for(room))` at both call sites plus `form.build(recipient)` → `form.build(recipient, by=request.user)`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest video/tests/ formation/ -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add video/forms_invitations.py video/forms_personal.py video/views_personal.py formation/views.py video/tests/test_group_invitations.py
git commit -m "feat(video): the invitation form takes a target (task #694)"
```

---

### Task 5: The entrances

**Files:**
- Create: `video/views_invitations.py`
- Modify: `video/views_personal.py` (drop `guest_room`, `_doorstep`; import the shared ones)
- Modify: `video/views.py` (`_render_room` invitation fallback)
- Modify: `video/urls.py`
- Create: `video/templates/video/invite/doorstep.html`, `video/templates/video/invite/invalid.html`
- Modify: `video/templates/video/personal/_waiting_poll.html` (reuse as-is if generic)
- Test: `video/tests/test_group_invitation_views.py`

**Interfaces:**
- Produces: URL names `video:guest_room` (unchanged path), `video:guest_presence`, `video:invitation_presence`, `video:invitation_revoke`, `video:workgroup_invite`, `video:event_invite`.

- [ ] **Step 1: Write the failing test**

```python
"""The entrances to a group's room for someone who is not in the group (task #694)."""
from __future__ import annotations

import pytest
from django.urls import reverse

from video import invitations as inv
from video.models import RoomInvitation

from .factories import daily_on, seminar, special_event, user

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _daily_on():
    with daily_on:
        yield


@pytest.fixture
def present(monkeypatch):
    state = {"live": False}
    monkeypatch.setattr(
        "video.services.room_participant_count", lambda room: 1 if state["live"] else 0
    )
    return state


@pytest.fixture
def stub_daily(monkeypatch):
    minted = {}

    def _get_room(name):
        return {"url": f"https://lsp.daily.co/{name}", "config": {}}

    def _token(*, room_name, user_name, is_owner, exp, **kwargs):
        minted.update(room=room_name, name=user_name, owner=is_owner)
        return "tok"

    monkeypatch.setattr("video.daily.get_room", _get_room)
    monkeypatch.setattr("video.daily.update_room", lambda name, props: _get_room(name))
    monkeypatch.setattr("video.daily.create_room", lambda name, properties=None: _get_room(name))
    monkeypatch.setattr("video.daily.create_meeting_token", _token)
    return minted


def group():
    return seminar().ensure_workgroup()


def test_an_invited_account_holder_uses_the_ordinary_room_url(client, stub_daily, present):
    wg = group()
    guest = user("guest@example.com")
    RoomInvitation.objects.create(workgroup=wg, invited_user=guest)
    client.force_login(guest)
    url = reverse("video:workgroup_room", args=[wg.slug])

    waiting = client.get(url)
    assert waiting.status_code == 200
    assert b"has not started" in waiting.content

    present["live"] = True
    assert client.get(url).status_code == 200
    assert stub_daily["owner"] is False


def test_an_uninvited_stranger_still_gets_403(client, stub_daily, present):
    wg = group()
    client.force_login(user("stranger@example.com"))
    present["live"] = True
    assert client.get(reverse("video:workgroup_room", args=[wg.slug])).status_code == 403


def test_the_guest_doorstep_mints_nothing_on_get(client, present, monkeypatch):
    wg = group()
    invitation = RoomInvitation.objects.create(
        workgroup=wg, token=RoomInvitation.new_token(), guest_name="Jane"
    )
    present["live"] = True

    def _boom(*a, **k):
        raise AssertionError("a GET must not mint a token")

    monkeypatch.setattr("video.daily.create_meeting_token", _boom)
    resp = client.get(reverse("video:guest_room", args=[invitation.token]))
    assert resp.status_code == 200


def test_a_guest_joins_a_group_room_by_posting_a_name(client, stub_daily, present):
    wg = group()
    invitation = RoomInvitation.objects.create(
        workgroup=wg, token=RoomInvitation.new_token(), guest_name="Jane"
    )
    present["live"] = True
    resp = client.post(
        reverse("video:guest_room", args=[invitation.token]),
        {"display_name": "Jane Doe"},
    )
    assert resp.status_code == 200
    assert stub_daily["name"] == "Jane Doe"
    assert stub_daily["owner"] is False


def test_the_presence_endpoint_needs_the_token(client, present):
    wg = group()
    invitation = RoomInvitation.objects.create(
        workgroup=wg, token=RoomInvitation.new_token(), guest_name="Jane"
    )
    assert client.get(reverse("video:guest_presence", args=["nonsense"])).status_code == 404
    ok = client.get(reverse("video:guest_presence", args=[invitation.token]))
    assert ok.json() == {"live": False}


def test_only_a_lead_may_invite(client, stub_daily):
    ev = seminar()
    wg = ev.ensure_workgroup()
    lead = user("lead@example.com", is_faculty=True)
    ev.add_faculty(lead)
    plain = user("plain@example.com")
    wg.add_member(plain)
    url = reverse("video:workgroup_invite", args=[wg.slug])

    client.force_login(plain)
    assert client.post(url, {"others": "Jane Doe"}).status_code == 403

    client.force_login(lead)
    assert client.post(url, {"others": "Jane Doe"}).status_code == 302
    assert RoomInvitation.objects.filter(workgroup=wg).count() == 1


def test_the_web_coordinator_may_invite(client, stub_daily):
    from core.models import StaffRole

    wg = group()
    coordinator = user("wc@example.com")
    role, _ = StaffRole.objects.get_or_create(
        key=StaffRole.WEB_COORDINATOR, defaults={"name": "Web Coordinator"}
    )
    role.holders.add(coordinator)
    client.force_login(coordinator)
    resp = client.post(reverse("video:workgroup_invite", args=[wg.slug]), {"others": "Jane Doe"})
    assert resp.status_code == 302
    assert RoomInvitation.objects.filter(workgroup=wg).count() == 1


def test_a_group_room_gains_no_daily_lobby():
    from video import services

    assert services._desired_properties(group())["enable_knocking"] is False


def test_revoke_is_refused_to_someone_else(client):
    wg = group()
    invitation = RoomInvitation.objects.create(
        workgroup=wg, token=RoomInvitation.new_token(), guest_name="Jane"
    )
    client.force_login(user("nobody@example.com"))
    resp = client.post(reverse("video:invitation_revoke", args=[invitation.pk]))
    assert resp.status_code == 403
    invitation.refresh_from_db()
    assert invitation.revoked_at is None
```

Check `Event.add_faculty`'s signature before using it (`grep -n "def add_faculty" events/models.py`).

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest video/tests/test_group_invitation_views.py -q`
Expected: FAIL — `Reverse for 'guest_presence' not found`.

- [ ] **Step 3: Write `video/views_invitations.py`**

The module owns the guest doorstep (for every target), the two presence
endpoints, invite and revoke. Key shapes:

```python
def guest_room(request, token):
    """The guest doorstep for any target, and the join it POSTs to.

    GET renders and mints nothing (link scanners pre-click these).
    """
    invitation = inv.guest_invitation(token)
    if invitation is None:
        return render(request, "video/invite/invalid.html", status=404)
    target = inv.target_of(invitation)
    if target.is_personal:
        return personal_guest_room(request, invitation)   # the #687 path, unchanged
    form = GuestJoinForm(request.POST or None,
                         initial={"display_name": invitation.guest_name})
    if request.method != "POST" or not form.is_valid():
        return _doorstep(request, invitation, target, form)
    try:
        inv.check_entry(target, request.user, invitation=invitation)
    except inv.EntryRefused as refused:
        return _doorstep(request, invitation, target, form, refused=refused)
    invitation.touch()
    return _join_as_guest(request, target, invitation,
                          form.cleaned_data["display_name"])
```

`_join_as_guest` calls `services.ensure_room(target.owner)`, falls back to
`video/room_unavailable.html` on None, mints via
`inv.guest_token(room, name, exp=services.token_exp_for(event), start_audio_off=off, start_video_off=off)`
where `off = services.spotlight_start_off(target.owner, False)` (the Daily client
takes the two flags separately, not a single `start_off`)
(where `event` is `target.owner` when it is an Event, else None), and renders
`video/room.html` with `is_owner=False`, `recording_available` read off the owner,
`auto_record=False`, `back_url=""`.

Presence:

```python
def guest_presence(request, token):
    invitation = inv.guest_invitation(token)
    if invitation is None:
        raise Http404
    return JsonResponse({"live": inv.target_of(invitation).someone_present()})


@login_required
def invitation_presence(request, pk):
    invitation = get_object_or_404(
        RoomInvitation, pk=pk, invited_user=request.user
    )
    if not invitation.is_live:
        raise Http404
    return JsonResponse({"live": inv.target_of(invitation).someone_present()})
```

Invite and revoke:

```python
@login_required
@require_POST
def workgroup_invite(request, slug):
    wg = get_object_or_404(Workgroup, slug=slug)
    return _invite(request, inv.target_for(wg), f"{wg.get_absolute_url()}?tab=meet")


@login_required
@require_POST
def event_invite(request, slug):
    event = get_object_or_404(Event, slug=slug)
    target = inv.target_for_event(event, create=True)
    if target is None or not isinstance(target, inv.EventTarget):
        # An offering meets in its workgroup's room; invite from the Workspace.
        raise Http404("This event has no room of its own.")
    return _invite(request, target, reverse("events:detail", args=[event.slug]) + "?view=faculty")


@login_required
@require_POST
def invitation_revoke(request, pk):
    invitation = get_object_or_404(RoomInvitation, pk=pk)
    target = inv.target_of(invitation)
    if not target.may_invite(request.user):
        raise PermissionDenied("You can't manage this room's invitations.")
    invitation.revoke()
    messages.success(request, f"{invitation.display_name}'s invitation was revoked.")
    return redirect(_back_to(target))
```

`_invite` mirrors `views_personal.room_invite` — `may_invite` or `PermissionDenied`, bind `InvitationForm(request.POST, target=target)`, loop recipients skipping `already_invited`, `form.build(recipient, by=request.user)`, send through the notifications module, and build the messages from the rows actually created. Reuse `views_personal._and_list` by moving it here and importing it there.

`views_personal.room_invite_revoke` is deleted; `formation/_tab_room.html` and any test naming `video:room_invite_revoke` move to `video:invitation_revoke`.

- [ ] **Step 4: Add the invitation fallback to `_render_room`**

In `video/views.py::_render_room`, replace the bare permission check:

```python
    invitation = None
    if not services.can_enter(room_owner, request.user):
        from . import invitations as inv

        target = inv.target_for(room_owner)
        invitation = inv.invitation_for(target, request.user)
        try:
            inv.check_entry(target, request.user, invitation=invitation)
        except inv.EntryRefused as refused:
            if not refused.waiting:
                raise PermissionDenied(str(refused)) from None
            return render(request, "video/invite/doorstep.html", {
                "target_label": target.label,
                "refused": refused,
                "poll_url": reverse("video:invitation_presence", args=[invitation.pk]),
                "back_url": back_url,
            })
```

and `invitation.touch()` once the room renders. The owner flag stays
`services.is_owner(room_owner, request.user)`, which is False for an invitee.

- [ ] **Step 5: Wire the URLs**

```python
    path("video/invitations/<int:pk>/revoke/", views_invitations.invitation_revoke, name="invitation_revoke"),
    path("video/invitations/<int:pk>/presence/", views_invitations.invitation_presence, name="invitation_presence"),
    path("meet/g/<slug:token>/presence/", views_invitations.guest_presence, name="guest_presence"),
    path("meet/g/<slug:token>/", views_invitations.guest_room, name="guest_room"),
    path("groups/<slug:slug>/room/invite/", views_invitations.workgroup_invite, name="workgroup_invite"),
    path("events/<slug:slug>/room/invite/", views_invitations.event_invite, name="event_invite"),
```

Keep `meet/g/<token>/presence/` **above** `meet/g/<token>/`, and both above `meet/<slug>/`.

- [ ] **Step 6: Write the two templates**

`video/invite/doorstep.html` — the group counterpart of
`video/personal/guest_doorstep.html`: name the group, say the meeting has not
started when waiting, render the `GuestJoinForm` when there is one, and include
`video/personal/_waiting_poll.html` when `poll_url` is set. `video/invite/invalid.html`
mirrors `guest_invalid.html`. Member-facing copy, commas not em dashes, and no
"analysands" line.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest video/tests/ -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add video/views_invitations.py video/views_personal.py video/views.py video/urls.py video/templates/video/invite formation/templates/formation/_tab_room.html video/tests/test_group_invitation_views.py
git commit -m "feat(video): invited outsiders can enter a group's room (task #694)"
```

---

### Task 6: Telling the person

**Files:**
- Create: `video/notifications_invitations.py` (generalized from `notifications_personal.py`, which is deleted)
- Modify: `video/views_personal.py`, `video/views_invitations.py`, `formation/views.py` (imports)
- Modify: `video/templates/video/email/guest_invitation.txt`
- Test: `video/tests/test_group_invitation_views.py` (append)

**Interfaces:**
- Produces: `send_invitation(invitation)`, `invitation_url(invitation)`.

- [ ] **Step 1: Write the failing test**

```python
def test_a_guest_invitation_emails_the_link_and_names_the_group(mailoutbox):
    from video.forms_invitations import InvitationForm, Recipient
    from video import notifications_invitations as notify

    wg = group()
    lead = user("lead@example.com")
    form = InvitationForm(target=inv.target_for(wg))
    invitation = form.build(
        Recipient(user=None, name="Jane Doe", email="jane@example.com"), by=lead
    )
    notify.send_invitation(invitation)
    assert len(mailoutbox) == 1
    assert wg.name in mailoutbox[0].body
    assert invitation.token in mailoutbox[0].body
    assert mailoutbox[0].reply_to == [lead.email]


def test_an_account_holder_gets_a_bell_row_pointing_at_the_room():
    from notifications.models import Notification
    from video import notifications_invitations as notify

    wg = group()
    guest = user("guest@example.com")
    invitation = RoomInvitation.objects.create(
        workgroup=wg, invited_user=guest, invited_by=user("lead@example.com")
    )
    notify.send_invitation(invitation)
    row = Notification.objects.filter(recipient=guest).first()
    assert row is not None
    assert wg.slug in row.url
```

Confirm `Notification`'s recipient field name with `grep -n "recipient\|user = " notifications/models.py | head`.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest video/tests/test_group_invitation_views.py -q -k "emails or bell"`
Expected: FAIL — `No module named 'video.notifications_invitations'`.

- [ ] **Step 3: Generalize the module**

`git mv video/notifications_personal.py video/notifications_invitations.py`, then:

- `invitation_url` uses `inv.target_of(invitation).room_url()` for the account-bound kind and the guest URL otherwise;
- the bell title becomes `f"{inviter} invited you to a meeting of {target.label}"` for a group target and keeps the #687 wording for a personal one, with `actor=invitation.invited_by or (room owner)`;
- the guest email subject/body name the target; `reply_to` is `[invitation.invited_by.email]` falling back to the personal room's owner, then `settings.SUPPORT_EMAIL`;
- the expiry line in `guest_invitation.txt` is wrapped in `{% if expires_at %}`.

Update the three importers.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest video/tests/ formation/ notifications/ -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add video/notifications_invitations.py video/views_personal.py video/views_invitations.py formation/views.py video/templates/video/email video/tests/test_group_invitation_views.py
git commit -m "feat(video): invitation mail and bells name the group (task #694)"
```

---

### Task 7: The panel, on three surfaces

**Files:**
- Create: `video/templates/video/_invitations_panel.html`
- Modify: `formation/templates/formation/_tab_room.html`, `formation/views.py`
- Modify: `workgroups/templates/workgroups/_tab_meet.html`, `workgroups/views.py`
- Modify: `events/templates/events/_faculty_tools.html`, `events/views.py`
- Test: `video/tests/test_group_invitation_views.py` (append), `core/test_templates.py` unaffected

**Interfaces:**
- Consumes: `invitations.target_for`, `InvitationForm`.
- Produces: a `room_invite_panel` context dict — `{"form", "invitations", "post_url", "heading", "intro"}` — rendered by the shared partial.

- [ ] **Step 1: Write the failing test**

```python
def test_the_meet_tab_offers_the_panel_to_a_lead_only(client, stub_daily):
    ev = seminar()
    wg = ev.ensure_workgroup()
    lead = user("lead@example.com", is_faculty=True)
    ev.add_faculty(lead)
    plain = user("plain@example.com")
    wg.add_member(plain)
    url = wg.get_absolute_url() + "?tab=meet"

    client.force_login(plain)
    assert b"Who else can join" not in client.get(url).content

    client.force_login(lead)
    assert b"Who else can join" in client.get(url).content


def test_an_offering_page_does_not_offer_an_event_invite_form(client, stub_daily):
    ev = seminar()
    wg = ev.ensure_workgroup()
    lead = user("lead@example.com", is_faculty=True)
    ev.add_faculty(lead)
    client.force_login(lead)
    resp = client.get(reverse("events:detail", args=[ev.slug]) + "?view=faculty", follow=True)
    assert b'action="/events/' not in resp.content or b"room/invite/" not in resp.content
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest video/tests/test_group_invitation_views.py -q -k "meet_tab or offering_page"`
Expected: FAIL — the panel is nowhere.

- [ ] **Step 3: Extract the partial**

Cut the "Who can join" `<section>` out of `formation/_tab_room.html` — form, member-filter script, invitation list, copy-link script — into `video/templates/video/_invitations_panel.html`, driving it from `panel.form`, `panel.invitations`, `panel.post_url`, `panel.heading`, `panel.intro`. Every revoke button posts to `{% url 'video:invitation_revoke' invitation.pk %}`. `_tab_room.html` then includes it with `{% include "video/_invitations_panel.html" with panel=room_invite_panel %}` and keeps its own heading copy through `panel.heading`/`panel.intro`. Nothing in the partial may name a personal room.

- [ ] **Step 4: Build the context in three views**

A shared helper in `video/invitations.py`:

```python
def panel_context(target, *, user, post_url, heading, intro):
    """The invite panel's context, or None when ``user`` may not invite."""
    if not target.may_invite(user):
        return None
    from .forms_invitations import InvitationForm
    from .notifications_invitations import invitation_url

    rows = list(target.live_invitations().order_by("-created_at"))
    for row in rows:
        row.share_url = invitation_url(row) if row.is_guest else ""
    return {
        "form": InvitationForm(target=target), "invitations": rows,
        "post_url": post_url, "heading": heading, "intro": intro,
    }
```

- `formation/views._formation_room_context` uses it with the #687 heading and intro and `post_url=reverse("video:room_invite")`.
- `workgroups/views.py`, in `elif active == "meet" and daily_on and is_member:`, adds
  `context["room_invite_panel"] = inv.panel_context(inv.target_for(wg), user=request.user, post_url=reverse("video:workgroup_invite", args=[wg.slug]), heading="Who else can join", intro="Invite someone from outside the group into this room. They can only join while someone is already in it.")`
- `events/views.py`, inside the `show_faculty_view` branch, sets the same for
  `target_for_event(event)` **only when the target is an `EventTarget`**, with
  `post_url=reverse("video:event_invite", args=[event.slug])`.

`_tab_meet.html` and `_faculty_tools.html` each render
`{% if room_invite_panel %}{% include "video/_invitations_panel.html" with panel=room_invite_panel %}{% endif %}`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest -q`
Expected: PASS (full suite — the partial extraction touches shipped templates).

- [ ] **Step 6: Commit**

```bash
git add video/templates/video/_invitations_panel.html video/invitations.py formation workgroups events video/tests/test_group_invitation_views.py
git commit -m "feat(video): leads invite from the Meet tab and the event page (task #694)"
```

---

### Task 8: Ship it

**Files:**
- Modify: `CLAUDE.md` (status log entry)
- Modify: `video/admin.py` (expose the new fields for staff)

- [ ] **Step 1: Add the admin fields**

`RoomInvitation`'s admin gains `workgroup`, `event`, `invited_by` in
`list_display` / `list_filter` / `raw_id_fields` as the existing rows are set up.

- [ ] **Step 2: Run everything**

Run: `uv run pytest -q && uv run ruff check .`
Expected: PASS, no lint findings.

- [ ] **Step 3: Write the CLAUDE.md status entry**

One entry in the house voice at the end of the "Done" list, headed
**"Inviting someone into a group's meeting room (task #694)"**, covering: the
gap (every group room admits only its own roster), the polymorphic target and
why not a second model, the invariant and why presence rather than a schedule,
`is_owner` as the inviter predicate, group links never expiring and why that is
safe, the offering-event target trap, and the context-gated faculty panel.

- [ ] **Step 4: Commit and merge**

```bash
git add CLAUDE.md video/admin.py
git commit -m "feat(video): external invitations for group meeting rooms (task #694)"
git checkout main && git merge --no-ff <branch> && git push
```

Resolve the near-certain `CLAUDE.md` conflict by keeping **both** entries in log
order (`claude-md-status-log-always-conflicts`).

- [ ] **Step 5: Verify the deploy**

`gh run list --workflow=Deploy --limit 3` until the run for this SHA is green.
A push to main is not a deploy (`pushed-is-not-deployed`).
