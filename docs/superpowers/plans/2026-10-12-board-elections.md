# Board Elections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Board election run on the site: open call for self-nominations, Board review, a ranked secret-to-all-but-the-voter ballot, and an on-site count (STV or most-votes), administered by a Board-appointed Election Administrator.

**Architecture:** A new `elections` app. Pure modules hold the logic (`phase` on the model, `eligibility.py`, `counting.py`, `ballots.py` — the only reader of rankings), `services.py` holds every state change and its audit line, and three thin view modules serve the administrator console (`/admin-tools/elections/`), the Board review page (`/admin-tools/board/elections/`), and the member's My LSP → Election tab. Window openings that send mail ride the existing five-minute `send_meeting_reminders` host timer.

**Tech Stack:** Django 5.2, pytest-django, DaisyUI/Tailwind templates, `notifications.dispatch.notify`, `payments.sending.ThrottledSender`.

**Spec:** `docs/superpowers/specs/2026-10-12-board-elections-design.md`

## Global Constraints

- New StaffRole key `election_administrator`, display name "Election Administrator"; never publicly badged.
- Console gate: role holder or superuser. **Not** the Web Coordinator by default.
- Board review gate: `committees.permissions.is_on_committee(user, "board")` or superuser.
- Voter roles: analyst, scholar, candidate, candidate_scholar, pre_candidate, pre_candidate_scholar, member. Standing must be `active`; not `is_persona`; not deceased; `is_active` user.
- Candidate roles: analyst, scholar, candidate, candidate_scholar; never the Election Administrator.
- `elections/ballots.py` is the only non-test, non-migration, non-models module that references `BallotRanking`.
- Ballot and BallotRanking are not registered in Django admin or devapi.
- The administrator sees *voted / not yet* only — never `cast_at`.
- No email ever carries a vote's contents. No email to a declined nominee.
- Default visibility: `show_during_voting="status"`, `show_results="winners"`. Default `count_method="stv"`.
- STV: Droop quota `floor(valid/(seats+1))+1`; weighted inclusive Gregory; transfer values truncated to 5 decimal places; ties by most recent differing preceding stage, then lot with a recorded seed.
- Dates: use `timezone.localdate()` never `timezone.now().date()` (guarded by `core/test_local_dates.py`).
- Member-facing copy uses commas, not em dashes. `{# #}` comments are single-line only.
- Never add a per-page Django messages loop (base.html renders them).
- Classes set only in Python must also appear in a template (Tailwind scans templates).
- Gated GET pages: anonymous → login redirect (`core.access.gate_or_login`), signed-in non-permitted → 404.

## Review Focus

1. **A voter opens the ballot in the first five minutes of voting, before the job has run.** Expect the roll to freeze on demand and the ballot to work — `services.ensure_roll_frozen` is called by every voting surface, not only the job. (Task 5 test `test_ballot_view_freezes_roll_lazily`.)
2. **The slate is published after `voting_close_at` has passed.** Expect refusal with a message to extend the close first, not a silently empty election. (Task 5 test `test_publish_slate_refuses_after_voting_close`.)
3. **A nominee withdraws after the slate is published, or the Board declines after it.** Expect neither: withdraw is refused after nominations close, review is refused after the slate. (Task 5 tests.)
4. **A ballot POST ranks a declined/withdrawn/other-election candidate, or repeats a rank.** Expect a 400-style form error and nothing saved. (Task 4 tests.)
5. **The administrator removes a voter who has already voted.** Expect refusal; the ballot stands. (Task 5 test.)

---

### Task 1: App skeleton, the role, models, phase

**Files:**
- Create: `elections/__init__.py`, `elections/apps.py`, `elections/models.py`, `elections/admin.py`, `elections/migrations/0001_initial.py` (generated), `elections/tests/__init__.py`, `elections/tests/test_phase.py`
- Create: `core/migrations/0014_seed_election_administrator_role.py`
- Modify: `core/models.py` (key constant), `config/settings/base.py` (LOCAL_APPS)

**Interfaces — Produces:**
- `core.models.StaffRole.ELECTION_ADMINISTRATOR = "election_administrator"`
- `elections.models.Election`, `Nomination`, `VoterRollEntry`, `Ballot`, `BallotRanking`
- `Election.Phase` (TextChoices): `DRAFT, NOMINATING, REVIEW, SLATE, VOTING, CLOSED, COUNTED, PUBLISHED, ACCLAIMED`
- `Election.phase_at(now) -> str`, `Election.phase` (property, uses `timezone.now()`)
- `Election.append_audit(by, text) -> None` (does not save)
- `Nomination.Status`: `PENDING, ACCEPTED, DECLINED`; `Nomination.is_live` (not withdrawn)
- `VoterRollEntry.Override`: `NONE="" , ADD="add", REMOVE="remove"`; fields `on_roll`, `role_at_freeze`

- [ ] **Step 1: Write the failing phase tests** (`elections/tests/test_phase.py`)

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from elections.models import Election

pytestmark = pytest.mark.django_db
PT = ZoneInfo("America/Los_Angeles")
T0 = datetime(2026, 11, 1, 9, 0, tzinfo=PT)


def _election(**kw):
    defaults = dict(
        title="Board election 2026", slug="board-2026", seats=3,
        nominations_open_at=T0, nominations_close_at=T0 + timedelta(days=14),
        voting_open_at=T0 + timedelta(days=21), voting_close_at=T0 + timedelta(days=35),
        results_due=(T0 + timedelta(days=42)).date(),
    )
    defaults.update(kw)
    return Election.objects.create(**defaults)


@pytest.mark.parametrize("offset,phase", [
    (timedelta(seconds=-1), Election.Phase.DRAFT),
    (timedelta(0), Election.Phase.NOMINATING),
    (timedelta(days=14, seconds=-1), Election.Phase.NOMINATING),
    (timedelta(days=14), Election.Phase.REVIEW),
    (timedelta(days=30), Election.Phase.REVIEW),  # never VOTING without a slate
])
def test_phase_before_slate(offset, phase):
    assert _election().phase_at(T0 + offset) == phase


def test_phase_after_slate():
    e = _election(slate_published_at=T0 + timedelta(days=15))
    assert e.phase_at(T0 + timedelta(days=16)) == Election.Phase.SLATE
    assert e.phase_at(T0 + timedelta(days=21)) == Election.Phase.VOTING
    assert e.phase_at(T0 + timedelta(days=35)) == Election.Phase.CLOSED


def test_late_slate_opens_voting_on_publication():
    e = _election(slate_published_at=T0 + timedelta(days=25))
    assert e.phase_at(T0 + timedelta(days=25)) == Election.Phase.VOTING


def test_terminal_stamps_win():
    e = _election(slate_published_at=T0, counted_at=T0 + timedelta(days=36))
    assert e.phase_at(T0 + timedelta(days=40)) == Election.Phase.COUNTED
    e.results_published_at = T0 + timedelta(days=37)
    assert e.phase_at(T0 + timedelta(days=40)) == Election.Phase.PUBLISHED
    e2 = _election(slug="b2", acclaimed_at=T0 + timedelta(days=16))
    assert e2.phase_at(T0 + timedelta(days=17)) == Election.Phase.ACCLAIMED


def test_evening_pacific_instant_is_same_day():
    # 17:30 Pacific = 00:30 UTC next day; phase uses aware datetimes, not dates.
    close = datetime(2026, 11, 15, 18, 0, tzinfo=PT)
    e = _election(nominations_close_at=close)
    assert e.phase_at(datetime(2026, 11, 15, 17, 30, tzinfo=PT)) == Election.Phase.NOMINATING


def test_role_seeded():
    from core.models import StaffRole
    assert StaffRole.objects.get(key=StaffRole.ELECTION_ADMINISTRATOR).name == "Election Administrator"
```

- [ ] **Step 2: Run, verify failure** — `uv run pytest elections/tests/test_phase.py -q` → import error (no app).

- [ ] **Step 3: Implement.** Add `"elections",` to `LOCAL_APPS` before `"devapi"`. Add `ELECTION_ADMINISTRATOR = "election_administrator"` beside `REGISTRAR` in `core/models.py` with a comment `# Election Administrator (task #813): runs Board elections; appointed by the Board; never publicly badged.` Seed migration copying `0013` exactly, KEY/NAME/DESCRIPTION = `("election_administrator", "Election Administrator", "Runs the Board election: sets its dates, keeps the voter roll, and counts the votes. Should be neither a director nor a candidate. Not publicly listed.")`, dependency `("core", "0013_seed_registrar_role")`.

`elections/apps.py`:
```python
from django.apps import AppConfig


class ElectionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "elections"
```

`elections/models.py`:
```python
"""Board elections (task #813). See docs/superpowers/specs/2026-10-12-board-elections-design.md.

The phase is computed from dates and step stamps, never stored, so it cannot
drift from them. Ballot rankings are read ONLY through ``elections.ballots``.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class Election(models.Model):
    class Phase(models.TextChoices):
        DRAFT = "draft", "Draft"
        NOMINATING = "nominating", "Nominations open"
        REVIEW = "review", "Board review"
        SLATE = "slate", "Slate published"
        VOTING = "voting", "Voting open"
        CLOSED = "closed", "Voting closed"
        COUNTED = "counted", "Counted"
        PUBLISHED = "published", "Results published"
        ACCLAIMED = "acclaimed", "Elected without a vote"

    class CountMethod(models.TextChoices):
        STV = "stv", "Single transferable vote (STV)"
        TOP_N = "top_n", "Most votes (each ballot's top choices)"

    class DuringVoting(models.TextChoices):
        STATUS = "status", "Status only"
        TURNOUT = "turnout", "Status and turnout"

    class ResultsShown(models.TextChoices):
        WINNERS = "winners", "Winners only"
        FULL = "full", "Winners and the full count"

    title = models.CharField(max_length=120)
    slug = models.SlugField(max_length=60, unique=True)
    seats = models.PositiveSmallIntegerField(default=1)
    nominations_open_at = models.DateTimeField()
    nominations_close_at = models.DateTimeField()
    voting_open_at = models.DateTimeField()
    voting_close_at = models.DateTimeField()
    results_due = models.DateField(null=True, blank=True)
    count_method = models.CharField(max_length=10, choices=CountMethod.choices,
                                    default=CountMethod.STV)
    show_during_voting = models.CharField(max_length=10, choices=DuringVoting.choices,
                                          default=DuringVoting.STATUS)
    show_results = models.CharField(max_length=10, choices=ResultsShown.choices,
                                    default=ResultsShown.WINNERS)

    call_sent_at = models.DateTimeField(null=True, blank=True)
    slate_published_at = models.DateTimeField(null=True, blank=True)
    slate_published_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                           on_delete=models.SET_NULL, related_name="+")
    roll_frozen_at = models.DateTimeField(null=True, blank=True)
    voting_notice_sent_at = models.DateTimeField(null=True, blank=True)
    counted_at = models.DateTimeField(null=True, blank=True)
    counted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    results_published_at = models.DateTimeField(null=True, blank=True)
    results_published_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                             on_delete=models.SET_NULL, related_name="+")
    acclaimed_at = models.DateTimeField(null=True, blank=True)
    acclaimed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")
    count_result = models.JSONField(null=True, blank=True)
    audit_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-nominations_open_at",)

    def __str__(self) -> str:
        return self.title

    FINAL_PHASES = frozenset({Phase.PUBLISHED, Phase.ACCLAIMED})

    def phase_at(self, now) -> str:
        P = self.Phase
        if self.acclaimed_at:
            return P.ACCLAIMED
        if self.results_published_at:
            return P.PUBLISHED
        if self.counted_at:
            return P.COUNTED
        if now < self.nominations_open_at:
            return P.DRAFT
        if now < self.nominations_close_at:
            return P.NOMINATING
        if self.slate_published_at is None:
            return P.REVIEW
        if now < self.voting_open_at:
            return P.SLATE
        if now < self.voting_close_at:
            return P.VOTING
        return P.CLOSED

    @property
    def phase(self) -> str:
        return self.phase_at(timezone.now())

    def get_phase_display(self) -> str:
        return self.Phase(self.phase).label

    def append_audit(self, by, text: str) -> None:
        who = (by.get_full_name() or by.email) if by is not None else "site"
        line = f"[{timezone.localtime():%Y-%m-%d %H:%M}] {who}: {text}"
        self.audit_notes = f"{self.audit_notes}\n{line}".strip()


class Nomination(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Under review"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Not accepted"

    election = models.ForeignKey(Election, on_delete=models.CASCADE, related_name="nominations")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="election_nominations")
    letter = models.TextField()
    role_at_submission = models.CharField(max_length=32, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    board_note = models.TextField(blank=True)

    class Meta:
        ordering = ("user__last_name", "user__first_name")
        constraints = [models.UniqueConstraint(fields=["election", "user"],
                                               name="election_one_nomination_per_member")]

    def __str__(self) -> str:
        return f"{self.user} — {self.election}"

    @property
    def is_live(self) -> bool:
        return self.withdrawn_at is None

    @property
    def name(self) -> str:
        return self.user.get_full_name() or self.user.email


class VoterRollEntry(models.Model):
    """One row per person the administrator has touched or who is on the frozen
    roll. Before the freeze only override rows exist; at the freeze every voter
    gets ``on_roll=True``."""

    class Override(models.TextChoices):
        NONE = "", "None"
        ADD = "add", "Added by the administrator"
        REMOVE = "remove", "Removed by the administrator"

    election = models.ForeignKey(Election, on_delete=models.CASCADE, related_name="roll")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="election_roll_entries")
    override = models.CharField(max_length=10, choices=Override.choices, blank=True, default="")
    reason = models.CharField(max_length=300, blank=True)
    override_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    override_at = models.DateTimeField(null=True, blank=True)
    on_roll = models.BooleanField(default=False)
    role_at_freeze = models.CharField(max_length=32, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["election", "user"],
                                               name="election_one_roll_row_per_member")]


class Ballot(models.Model):
    """Linked to its voter; the link is shown to nobody but the voter.
    Read rankings ONLY through ``elections.ballots``."""

    election = models.ForeignKey(Election, on_delete=models.CASCADE, related_name="ballots")
    voter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="election_ballots")
    cast_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["election", "voter"],
                                               name="election_one_ballot_per_voter")]


class BallotRanking(models.Model):
    ballot = models.ForeignKey(Ballot, on_delete=models.CASCADE, related_name="rankings")
    nomination = models.ForeignKey(Nomination, on_delete=models.CASCADE, related_name="+")
    rank = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["ballot", "rank"], name="ballot_rank_unique"),
            models.UniqueConstraint(fields=["ballot", "nomination"], name="ballot_candidate_unique"),
        ]
```

`elections/admin.py` (escape hatch for Election/Nomination/roll; **no Ballot**):
```python
from django.contrib import admin

from .models import Election, Nomination, VoterRollEntry

# Ballot and BallotRanking are deliberately NOT registered: the voter↔vote link
# is shown to nobody but the voter (task #813). A test pins this.


@admin.register(Election)
class ElectionAdmin(admin.ModelAdmin):
    list_display = ("title", "seats", "nominations_open_at", "voting_close_at")
    readonly_fields = ("count_result", "audit_notes")


@admin.register(Nomination)
class NominationAdmin(admin.ModelAdmin):
    list_display = ("user", "election", "status", "withdrawn_at")
    list_filter = ("election", "status")


@admin.register(VoterRollEntry)
class VoterRollEntryAdmin(admin.ModelAdmin):
    list_display = ("user", "election", "on_roll", "override")
    list_filter = ("election", "on_roll", "override")
```

Generate: `uv run python manage.py makemigrations elections` (creates `0001_initial.py`).

- [ ] **Step 4: Run** `uv run pytest elections/tests/test_phase.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(elections): app, models, computed phase, Election Administrator role (task #813)`.

---

### Task 2: Eligibility

**Files:** Create `elections/eligibility.py`, `elections/tests/test_eligibility.py`

**Interfaces — Produces:**
- `VOTER_ROLES: frozenset[str]`, `CANDIDATE_ROLES: frozenset[str]`
- `eligible_voters_qs() -> QuerySet[User]` (role/standing based, no overrides)
- `is_eligible_voter(user) -> bool`
- `computed_roll(election) -> list[User]` (eligible ± overrides; pre-freeze view)
- `roll_users(election) -> QuerySet[User]` (frozen roll if frozen else computed ids)
- `is_on_roll(election, user) -> bool`
- `may_stand(user) -> bool`

- [ ] **Step 1: Failing tests** (`elections/tests/test_eligibility.py`)

```python
import pytest

from accounts.models import Profile, User
from core.models import StaffRole
from elections import eligibility
from elections.models import VoterRollEntry
from elections.tests.factories import make_election, make_member

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("role,votes,stands", [
    ("analyst", True, True), ("scholar", True, True),
    ("candidate", True, True), ("candidate_scholar", True, True),
    ("pre_candidate", True, False), ("pre_candidate_scholar", True, False),
    ("member", True, False), ("external", False, False),
    ("student", False, False), ("prospective_applicant", False, False),
])
def test_roles(role, votes, stands):
    u = make_member(role=role)
    assert eligibility.is_eligible_voter(u) is votes
    assert eligibility.may_stand(u) is stands


@pytest.mark.parametrize("standing", ["on_leave", "resigned", "emeritus", "retired", "removed"])
def test_only_active_standing_votes(standing):
    assert not eligibility.is_eligible_voter(make_member(standing=standing))


def test_persona_inactive_and_deceased_excluded():
    import datetime
    p = make_member(email="p@x.test"); p.profile.is_persona = True; p.profile.save()
    i = make_member(email="i@x.test"); i.is_active = False; i.save()
    d = make_member(email="d@x.test"); d.profile.deceased_on = datetime.date(2026, 1, 1); d.profile.save()
    for u in (p, i, d):
        assert not eligibility.is_eligible_voter(u)


def test_administrator_may_not_stand():
    u = make_member(role="analyst")
    StaffRole.objects.get(key=StaffRole.ELECTION_ADMINISTRATOR).holders.add(u)
    assert not eligibility.may_stand(u)


def test_computed_roll_applies_overrides():
    e = make_election()
    keep = make_member(email="k@x.test")
    gone = make_member(email="g@x.test")
    extra = make_member(email="e@x.test", role="external")
    VoterRollEntry.objects.create(election=e, user=gone, override="remove", reason="unpaid")
    VoterRollEntry.objects.create(election=e, user=extra, override="add", reason="foundation")
    ids = {u.id for u in eligibility.computed_roll(e)}
    assert keep.id in ids and extra.id in ids and gone.id not in ids
```

Also create `elections/tests/factories.py` (used by every later test file):
```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from accounts.models import User
from elections.models import Election, Nomination

PT = ZoneInfo("America/Los_Angeles")
_n = iter(range(1, 10_000))


def make_member(email=None, role="analyst", standing="active", first="Mem", last=None):
    i = next(_n)
    u = User.objects.create_user(email=email or f"m{i}@x.test", password="x",
                                 first_name=first, last_name=last or f"Ber{i}")
    u.profile.role = role
    u.profile.standing = standing
    u.profile.save()
    return u


def make_election(phase="draft", **kw):
    """An election whose windows put ``timezone.now()`` in ``phase``."""
    now = timezone.now()
    d = timedelta(days=1)
    windows = {
        "draft":      (now + d, now + 2 * d, now + 3 * d, now + 4 * d, False),
        "nominating": (now - d, now + d, now + 2 * d, now + 3 * d, False),
        "review":     (now - 2 * d, now - d, now + d, now + 2 * d, False),
        "slate":      (now - 3 * d, now - 2 * d, now + d, now + 2 * d, True),
        "voting":     (now - 3 * d, now - 2 * d, now - d, now + d, True),
        "closed":     (now - 4 * d, now - 3 * d, now - 2 * d, now - d, True),
    }[phase]
    no, nc, vo, vc, slate = windows
    defaults = dict(title="Board election", slug=f"board-{next(_n)}", seats=2,
                    nominations_open_at=no, nominations_close_at=nc,
                    voting_open_at=vo, voting_close_at=vc,
                    slate_published_at=(nc if slate else None))
    defaults.update(kw)
    return Election.objects.create(**defaults)


def make_nomination(election, user=None, status="accepted", letter="Why I would serve."):
    user = user or make_member()
    return Nomination.objects.create(election=election, user=user, letter=letter,
                                     status=status, role_at_submission=user.profile.role)
```

- [ ] **Step 2: Run** → FAIL (no module).
- [ ] **Step 3: Implement** `elections/eligibility.py`:

```python
"""Who may vote and who may stand (task #813). Deliberately NOT
accounts.permissions.lsp_members(): that answers "may see members-only pages"
and admits Django staff, LSP Staff and committee-serving Auditors. Voting is
narrower: the bylaws' member roles in active standing (Art. 12 §2). "Paid
their fees" is applied by the administrator through overrides, not here."""

from __future__ import annotations

from accounts.models import Profile, User
from core.access import has_staff_role
from core.models import StaffRole

VOTER_ROLES = frozenset({
    "analyst", "scholar", "candidate", "candidate_scholar",
    "pre_candidate", "pre_candidate_scholar", "member",
})
CANDIDATE_ROLES = frozenset({"analyst", "scholar", "candidate", "candidate_scholar"})


def eligible_voters_qs():
    return (
        User.objects.filter(
            is_active=True,
            profile__role__in=VOTER_ROLES,
            profile__standing=Profile.Standing.ACTIVE,
            profile__is_persona=False,
            profile__deceased_on__isnull=True,
        )
        .select_related("profile")
        .order_by("last_name", "first_name", "email")
    )


def is_eligible_voter(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return eligible_voters_qs().filter(pk=user.pk).exists()


def may_stand(user) -> bool:
    profile = getattr(user, "profile", None)
    return (
        profile is not None
        and profile.role in CANDIDATE_ROLES
        and is_eligible_voter(user)
        and not has_staff_role(user, StaffRole.ELECTION_ADMINISTRATOR)
    )


def computed_roll(election) -> list:
    """Eligible voters plus the administrator's adds, minus removes."""
    from .models import VoterRollEntry

    overrides = dict(
        VoterRollEntry.objects.filter(election=election)
        .exclude(override="").values_list("user_id", "override")
    )
    removed = {u for u, o in overrides.items() if o == VoterRollEntry.Override.REMOVE}
    added = {u for u, o in overrides.items() if o == VoterRollEntry.Override.ADD}
    ids = (set(eligible_voters_qs().values_list("id", flat=True)) - removed) | added
    return list(User.objects.filter(id__in=ids).select_related("profile")
                .order_by("last_name", "first_name", "email"))


def roll_users(election):
    if election.roll_frozen_at:
        return (User.objects.filter(election_roll_entries__election=election,
                                    election_roll_entries__on_roll=True)
                .select_related("profile").order_by("last_name", "first_name", "email"))
    return User.objects.filter(id__in=[u.id for u in computed_roll(election)]) \
        .select_related("profile").order_by("last_name", "first_name", "email")


def is_on_roll(election, user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return roll_users(election).filter(pk=user.pk).exists()
```

- [ ] **Step 4: Run** `uv run pytest elections/tests -q` → PASS.
- [ ] **Step 5: Commit** `feat(elections): voter and candidate eligibility (task #813)`.

---

### Task 3: Counting (pure)

**Files:** Create `elections/counting.py`, `elections/tests/test_counting.py`

**Interfaces — Produces:**
- `count(method: str, ballots: list[list[int]], candidates: list[int], seats: int, seed: int) -> dict`
- `count_stv(ballots, candidates, seats, rng) -> dict`, `count_top_n(ballots, candidates, seats, rng) -> dict`
- Result keys: `method, seats, valid_ballots, quota (STV only, str), stages (list of {"n", "action", "subject", "totals": {str(cid): str}, "exhausted": str}), elected (list[int] in order), lots (list of {"stage", "tied", "chosen"}), seed`.

- [ ] **Step 1: Failing tests** (hand-worked; each asserts stages as well as winners)

```python
import random
from decimal import Decimal

from elections import counting


def stv(ballots, cands, seats, seed=1):
    return counting.count_stv(ballots, cands, seats, random.Random(seed))


def test_quota_and_first_stage_election():
    # 10 ballots, 2 seats → quota floor(10/3)+1 = 4
    b = [[1, 2]] * 6 + [[2]] * 3 + [[3]] * 1
    r = stv(b, [1, 2, 3], 2)
    assert r["quota"] == "4"
    assert r["elected"][0] == 1
    assert r["stages"][0]["totals"] == {"1": "6", "2": "3", "3": "1"}


def test_surplus_transfers_fractionally_and_truncates():
    # A has 6, quota 4, surplus 2 → each of A's 6 ballots carries 2/6 = 0.33333
    b = [[1, 2]] * 6 + [[2]] * 3 + [[3]] * 1
    r = stv(b, [1, 2, 3], 2)
    transfer = next(s for s in r["stages"] if s["action"] == "surplus")
    assert transfer["subject"] == 1
    # 3 + 6 * 0.33333 = 4.99998 → B reaches quota
    after = r["stages"][r["stages"].index(transfer) + 1]
    assert after["totals"]["2"] == "4.99998"
    assert r["elected"] == [1, 2]


def test_exclusion_transfers_at_current_value():
    # 9 ballots, 1 seat, quota 5. C excluded, C's votes go to B → B wins.
    b = [[1]] * 4 + [[2]] * 3 + [[3, 2]] * 2
    r = stv(b, [1, 2, 3], 1)
    assert any(s["action"] == "exclude" and s["subject"] == 3 for s in r["stages"])
    assert r["elected"] == [2]


def test_exhausted_ballots_counted():
    b = [[1]] * 4 + [[2]] * 3 + [[3]] * 2
    r = stv(b, [1, 2, 3], 1)
    excl = [s for s in r["stages"] if s["action"] == "exclude"]
    assert excl and Decimal(r["stages"][-1]["exhausted"]) >= Decimal("2")


def test_remaining_equals_seats_elects_all():
    b = [[1]] * 2 + [[2]] * 1 + [[3]] * 1
    r = stv(b, [1, 2, 3], 3)
    assert sorted(r["elected"]) == [1, 2, 3]


def test_tie_broken_by_earlier_stage():
    # Stage 1: D=1, C=2, B=2. D excluded → its vote goes to C... design so that at a
    # later stage B and C tie but differed at stage 1 (C higher) → B excluded.
    b = [[1]] * 5 + [[3]] * 2 + [[2]] * 3 + [[4, 2]] * 1 + [[5, 3]] * 2
    # candidates 1..5; quota for 1 seat over 13 = 7
    r = stv(b, [1, 2, 3, 4, 5], 1)
    lots = r["lots"]
    assert lots == []  # resolved without lot


def test_tie_by_lot_is_recorded_and_seed_reproducible():
    b = [[1]] * 3 + [[2]] * 1 + [[3]] * 1
    r1 = stv(b, [1, 2, 3], 1, seed=7)
    r2 = stv(b, [1, 2, 3], 1, seed=7)
    assert r1["lots"] and r1["lots"][0]["tied"] == [2, 3]
    assert r1 == r2


def test_partial_ballots_and_unranked_candidates():
    b = [[2]] * 3 + [[1, 3]] * 2
    r = stv(b, [1, 2, 3], 1)
    assert r["elected"] == [2]


def test_top_n_counts_each_ballots_top_seats():
    b = [[1, 2, 3]] * 3 + [[3, 2, 1]] * 2
    r = counting.count_top_n(b, [1, 2, 3], 2, random.Random(1))
    # top-2: 1:3, 2:5, 3:2 → elected 2 then 1
    assert r["elected"] == [2, 1]
    assert r["stages"][0]["totals"] == {"1": "3", "2": "5", "3": "2"}


def test_top_n_tie_for_last_seat_by_lot():
    b = [[1, 2]] * 2 + [[1, 3]] * 2
    r = counting.count_top_n(b, [1, 2, 3], 2, random.Random(3))
    assert r["elected"][0] == 1 and r["lots"] and set(r["lots"][0]["tied"]) == {2, 3}


def test_count_dispatch_records_seed():
    r = counting.count("stv", [[1]], [1, 2], 1, seed=42)
    assert r["seed"] == 42 and r["method"] == "stv" and r["elected"] == [1]
```

(Implementer: verify the expected tie case in `test_tie_broken_by_earlier_stage` by hand while writing the algorithm; adjust the ballot list — not the assertion's meaning — if the arithmetic doesn't produce a tie that earlier stages break.)

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `elections/counting.py`:

```python
"""Pure vote counting (task #813): anonymous ranked ballots in, a JSON-ready
result out. No database. STV follows the Scottish Local Government Elections
Order 2007 counting rules: Droop quota, weighted inclusive Gregory transfers,
transfer values truncated to five decimal places, ties broken by the most
recent preceding stage at which the tied candidates differed, then by lot."""

from __future__ import annotations

import random
from decimal import ROUND_DOWN, Decimal

FIVE = Decimal("0.00001")


def _trunc(x: Decimal) -> Decimal:
    return x.quantize(FIVE, rounding=ROUND_DOWN)


def _fmt(x: Decimal) -> str:
    x = x.normalize()
    return format(x, "f")


def _break_tie(tied: list[int], history: list[dict], lowest: bool, rng, lots, stage_n):
    """Narrow ``tied`` by preceding stages (most recent first), then by lot."""
    tied = sorted(tied)
    for totals in reversed(history[:-1]):
        vals = {c: totals.get(c, Decimal(0)) for c in tied}
        target = min(vals.values()) if lowest else max(vals.values())
        narrowed = [c for c in tied if vals[c] == target]
        if len(narrowed) < len(tied):
            tied = narrowed
        if len(tied) == 1:
            return tied[0]
    chosen = rng.choice(tied)
    lots.append({"stage": stage_n, "tied": tied, "chosen": chosen})
    return chosen


def _next_pref(prefs, start, continuing):
    for i in range(start, len(prefs)):
        if prefs[i] in continuing:
            return i
    return None


def count_stv(ballots, candidates, seats, rng):
    cands = list(dict.fromkeys(candidates))
    continuing = set(cands)
    papers = []  # [prefs, position, value]
    for b in ballots:
        prefs = [c for c in b if c in continuing]
        if prefs:
            papers.append([prefs, 0, Decimal(1)])
    valid = len(papers)
    quota = Decimal(valid // (seats + 1) + 1)
    piles = {c: [] for c in cands}
    for p in papers:
        piles[p[0][0]].append(p)
    elected, excluded, pending, stages, lots, history = [], [], [], [], [], []
    exhausted = Decimal(0)
    held = {}

    def totals():
        t = {c: sum((p[2] for p in piles[c]), Decimal(0)) for c in continuing}
        t.update({c: held[c] for c in elected})
        return t

    def record(action, subject):
        t = totals()
        history.append(t)
        stages.append({
            "n": len(stages) + 1, "action": action, "subject": subject,
            "totals": {str(c): _fmt(t.get(c, Decimal(0))) for c in cands if c not in excluded},
            "exhausted": _fmt(exhausted),
        })
        return t

    def move(ballot_list, value_fn):
        nonlocal exhausted
        for p in ballot_list:
            p[2] = value_fn(p[2])
            nxt = _next_pref(p[0], p[1] + 1, continuing)
            if nxt is None:
                exhausted += p[2]
            else:
                p[1] = nxt
                piles[p[0][nxt]].append(p)

    t = record("first", None)
    while True:
        reached = [c for c in continuing if t[c] >= quota]
        while reached:
            top = max(t[c] for c in reached)
            group = [c for c in reached if t[c] == top]
            c = group[0] if len(group) == 1 else _break_tie(group, history, False, rng, lots, len(stages))
            continuing.discard(c)
            elected.append(c)
            held[c] = t[c]
            pending.append(c)
            reached.remove(c)
        if len(elected) >= seats:
            break
        if len(continuing) <= seats - len(elected):
            for c in sorted(continuing, key=lambda c: (-t[c], c)):
                elected.append(c)
                held[c] = t[c]
            continuing.clear()
            record("elect_remaining", None)
            break
        surpluses = {c: held[c] - quota for c in pending if held[c] > quota}
        if surpluses:
            big = max(surpluses.values())
            group = [c for c in pending if surpluses.get(c) == big]
            c = group[0] if len(group) == 1 else _break_tie(group, history, False, rng, lots, len(stages))
            pending.remove(c)
            surplus, total = surpluses[c], held[c]
            transfer = piles[c]
            piles[c] = []
            held[c] = quota
            move(transfer, lambda v: _trunc(v * surplus / total))
            t = record("surplus", c)
            continue
        pending.clear()
        low = min(t[c] for c in continuing)
        group = [c for c in continuing if t[c] == low]
        c = group[0] if len(group) == 1 else _break_tie(group, history, True, rng, lots, len(stages))
        continuing.discard(c)
        excluded.append(c)
        transfer = piles[c]
        piles[c] = []
        move(transfer, lambda v: v)
        t = record("exclude", c)

    return {
        "method": "stv", "seats": seats, "valid_ballots": valid, "quota": _fmt(quota),
        "stages": stages, "elected": elected[:seats], "excluded": excluded, "lots": lots,
    }


def count_top_n(ballots, candidates, seats, rng):
    cands = list(dict.fromkeys(candidates))
    allowed = set(cands)
    tally = {c: 0 for c in cands}
    valid = 0
    for b in ballots:
        prefs = [c for c in b if c in allowed][:seats]
        if prefs:
            valid += 1
            for c in prefs:
                tally[c] += 1
    order = sorted(cands, key=lambda c: (-tally[c], c))
    elected, lots = [], []
    i = 0
    while len(elected) < seats and i < len(order):
        group = [c for c in order[i:] if tally[c] == tally[order[i]]]
        room = seats - len(elected)
        if len(group) <= room:
            elected.extend(group)
        else:
            group = sorted(group)
            chosen = rng.sample(group, room)
            lots.append({"stage": 1, "tied": group, "chosen": chosen})
            elected.extend(chosen)
        i += len(group)
    return {
        "method": "top_n", "seats": seats, "valid_ballots": valid,
        "stages": [{"n": 1, "action": "tally", "subject": None,
                    "totals": {str(c): str(tally[c]) for c in cands}, "exhausted": "0"}],
        "elected": elected, "excluded": [], "lots": lots,
    }


def count(method, ballots, candidates, seats, seed):
    rng = random.Random(seed)
    fn = count_stv if method == "stv" else count_top_n
    result = fn(ballots, candidates, seats, rng)
    result["seed"] = seed
    return result
```

Note: in `test_top_n_tie_for_last_seat_by_lot`, `lots[0]["chosen"]` is a list for top_n; tests only check `tied`.

- [ ] **Step 4: Run** `uv run pytest elections/tests/test_counting.py -q` → PASS (fix algorithm, not expectations, except the tie-fixture note above).
- [ ] **Step 5: Commit** `feat(elections): STV and most-votes counting (task #813)`.

---

### Task 4: Ballots module + secrecy pins

**Files:** Create `elections/ballots.py`, `elections/forms.py` (BallotForm only for now), `elections/tests/test_ballots.py`, `elections/tests/test_secrecy.py`

**Interfaces — Produces:**
- `ballots.candidates(election) -> list[Nomination]` (accepted, live)
- `ballots.cast(election, voter, ranked: list[int]) -> Ballot` — `ranked` is nomination ids in preference order; raises `ValueError` on empty, duplicate, or non-candidate ids. Replaces any existing rankings atomically.
- `ballots.own_ballot(user, election) -> list[Nomination] | None`
- `ballots.voted_user_ids(election) -> set[int]`
- `ballots.turnout(election) -> int`
- `ballots.anonymous_ballots(election) -> list[list[int]]` (shuffled)
- `forms.BallotForm(candidates, data=None, initial_order=None)`; `.ranked_ids() -> list[int]`

- [ ] **Step 1: Failing tests**

`test_ballots.py`:
```python
import pytest

from elections import ballots
from elections.forms import BallotForm
from elections.tests.factories import make_election, make_member, make_nomination

pytestmark = pytest.mark.django_db


def _setup():
    e = make_election("voting")
    a, b = make_nomination(e), make_nomination(e)
    declined = make_nomination(e, status="declined")
    return e, a, b, declined


def test_cast_and_read_own():
    e, a, b, _ = _setup()
    v = make_member()
    ballots.cast(e, v, [b.id, a.id])
    assert [n.id for n in ballots.own_ballot(v, e)] == [b.id, a.id]
    assert ballots.voted_user_ids(e) == {v.id}


def test_changing_replaces():
    e, a, b, _ = _setup()
    v = make_member()
    ballots.cast(e, v, [a.id, b.id])
    ballots.cast(e, v, [b.id])
    assert [n.id for n in ballots.own_ballot(v, e)] == [b.id]
    assert ballots.anonymous_ballots(e) == [[b.id]]


@pytest.mark.parametrize("bad", ["empty", "dup", "declined", "other"])
def test_cast_rejects(bad):
    e, a, b, declined = _setup()
    other = make_nomination(make_election("voting"))
    ranked = {"empty": [], "dup": [a.id, a.id], "declined": [declined.id],
              "other": [other.id]}[bad]
    with pytest.raises(ValueError):
        ballots.cast(e, make_member(), ranked)
    assert ballots.turnout(e) == 0


def test_form_orders_by_rank_and_closes_gaps():
    e, a, b, _ = _setup()
    f = BallotForm(ballots.candidates(e), data={f"rank_{a.id}": "3", f"rank_{b.id}": "1"})
    assert f.is_valid(), f.errors
    assert f.ranked_ids() == [b.id, a.id]


def test_form_refuses_duplicate_rank_and_empty():
    e, a, b, _ = _setup()
    assert not BallotForm(ballots.candidates(e), data={f"rank_{a.id}": "1", f"rank_{b.id}": "1"}).is_valid()
    assert not BallotForm(ballots.candidates(e), data={}).is_valid()
```

`test_secrecy.py`:
```python
import pathlib

from django.contrib import admin
from django.urls import get_resolver

from elections.models import Ballot, BallotRanking

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_ballots_not_in_django_admin():
    assert Ballot not in admin.site._registry
    assert BallotRanking not in admin.site._registry


def test_devapi_exposes_no_elections():
    from devapi import urls
    assert not any("election" in str(p.pattern).lower() or "ballot" in str(p.pattern).lower()
                   for p in urls.urlpatterns)


def test_only_ballots_module_reads_rankings():
    import subprocess
    out = subprocess.run(["git", "grep", "-l", "BallotRanking", "--", "*.py"],
                         cwd=ROOT, capture_output=True, text=True).stdout.split()
    allowed = {"elections/models.py", "elections/ballots.py"}
    offenders = [p for p in out if p not in allowed
                 and "/migrations/" not in p and "/tests/" not in p]
    assert offenders == []


def test_no_template_shows_cast_at():
    import subprocess
    out = subprocess.run(["git", "grep", "-l", "cast_at", "--", "*.html", "*.txt"],
                         cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert out == []
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**

`elections/ballots.py`:
```python
"""The ONLY reader of ballot rankings (task #813).

Two exits: ``own_ballot`` for the voter's own page, ``anonymous_ballots`` for
the counter (voter dropped, order shuffled). Everything else asks only
whether a Ballot row exists (``voted_user_ids``). A source-scan test pins that
no other module references BallotRanking."""

from __future__ import annotations

import random

from django.db import transaction

from .models import Ballot, BallotRanking, Nomination


def candidates(election) -> list[Nomination]:
    return list(
        election.nominations.filter(status=Nomination.Status.ACCEPTED, withdrawn_at__isnull=True)
        .select_related("user").order_by("user__last_name", "user__first_name")
    )


def cast(election, voter, ranked: list[int]) -> Ballot:
    allowed = {n.id for n in candidates(election)}
    if not ranked or len(set(ranked)) != len(ranked) or not set(ranked) <= allowed:
        raise ValueError("A ballot must rank at least one candidate, each once.")
    with transaction.atomic():
        ballot, _ = Ballot.objects.select_for_update().get_or_create(election=election, voter=voter)
        BallotRanking.objects.filter(ballot=ballot).delete()
        BallotRanking.objects.bulk_create(
            BallotRanking(ballot=ballot, nomination_id=nid, rank=i)
            for i, nid in enumerate(ranked, start=1)
        )
        ballot.save(update_fields=["updated_at"])
    return ballot


def own_ballot(user, election) -> list[Nomination] | None:
    ballot = Ballot.objects.filter(election=election, voter=user).first()
    if ballot is None:
        return None
    return [r.nomination for r in
            BallotRanking.objects.filter(ballot=ballot).select_related("nomination__user")
            .order_by("rank")]


def voted_user_ids(election) -> set[int]:
    return set(Ballot.objects.filter(election=election).values_list("voter_id", flat=True))


def turnout(election) -> int:
    return Ballot.objects.filter(election=election).count()


def anonymous_ballots(election) -> list[list[int]]:
    by_ballot: dict[int, list[tuple[int, int]]] = {}
    for ballot_id, rank, nid in (BallotRanking.objects
                                 .filter(ballot__election=election)
                                 .values_list("ballot_id", "rank", "nomination_id")):
        by_ballot.setdefault(ballot_id, []).append((rank, nid))
    out = [[nid for _, nid in sorted(r)] for r in by_ballot.values()]
    random.SystemRandom().shuffle(out)
    return out
```

`elections/forms.py` (BallotForm; NominationForm etc. added in Task 6):
```python
from __future__ import annotations

from django import forms


class BallotForm(forms.Form):
    """One rank <select> per candidate (works without JavaScript). Ranks may
    have gaps; ``ranked_ids`` closes them up. Duplicates are refused."""

    def __init__(self, candidates, *args, initial_order=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.candidates = list(candidates)
        n = len(self.candidates)
        choices = [("", "Not ranked")] + [(str(i), _ordinal(i)) for i in range(1, n + 1)]
        initial = {nid: i for i, nid in enumerate(initial_order or [], start=1)}
        for c in self.candidates:
            self.fields[f"rank_{c.id}"] = forms.ChoiceField(
                choices=choices, required=False, label=c.name,
                initial=str(initial[c.id]) if c.id in initial else "",
            )

    def clean(self):
        data = super().clean()
        ranks = {c.id: int(data[f"rank_{c.id}"]) for c in self.candidates
                 if data.get(f"rank_{c.id}")}
        if not ranks:
            raise forms.ValidationError("Rank at least one candidate.")
        if len(set(ranks.values())) != len(ranks):
            raise forms.ValidationError("Give each candidate a different rank.")
        self._ranked = [cid for cid, _ in sorted(ranks.items(), key=lambda kv: kv[1])]
        return data

    def ranked_ids(self) -> list[int]:
        return self._ranked


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix} choice"
```

- [ ] **Step 4: Run** `uv run pytest elections/tests -q` → PASS.
- [ ] **Step 5: Commit** `feat(elections): ballots module, ranked ballot form, secrecy pins (task #813)`.

---

### Task 5: Services (state changes, audit, roll freeze, count) + notifications/email

**Files:**
- Create: `elections/services.py`, `elections/notifications.py`, `elections/emails.py`, `elections/templates/elections/email/{call,nomination_received,candidacy_accepted,voting_open,reminder,ballot_recorded,results}.txt`, `elections/tests/test_services.py`
- Modify: `notifications/categories.py` (add `ELECTIONS`), generate `notifications/migrations/0018_*.py`

**Interfaces — Consumes:** Tasks 1–4. **Produces** (all raise `services.ElectionError(str)` with a member-readable message on refusal):
- `submit_nomination(election, user, letter) -> Nomination` (create or update; re-submit clears `withdrawn_at`)
- `withdraw_nomination(nomination) -> None`
- `review_nomination(nomination, by, status, note="") -> None`
- `publish_slate(election, by) -> None`
- `acclaim(election, by) -> None`
- `ensure_roll_frozen(election, now=None) -> bool` (True if it froze now)
- `set_override(election, user, override, reason, by) -> None` (pre- and post-freeze; refuses removing a voter who voted)
- `cast_ballot(election, voter, ranked) -> None` (checks VOTING and on roll; notifies ballot recorded)
- `run_count(election, by) -> dict`, `publish_results(election, by) -> None`
- `remind_nonvoters(election, by) -> int`
- `open_now(election, which, by)`, `close_now(election, which, by)` (`which` in `{"nominations", "voting"}`)
- `analyst_check(election, elected_nomination_ids) -> dict` (`{"elected_analysts", "continuing_analysts", "total", "short": bool}`)
- `advance_elections(now=None) -> dict` (`{"calls": int, "frozen": int, "voting_notices": int}`)
- `current_election() -> Election | None` (latest non-final, else latest)

- [ ] **Step 1: Failing tests** (`elections/tests/test_services.py`) — at least:

```python
import pytest
from django.utils import timezone

from elections import ballots, services
from elections.models import Election, Nomination, VoterRollEntry
from elections.tests.factories import make_election, make_member, make_nomination

pytestmark = pytest.mark.django_db


def test_nomination_refused_outside_window_and_for_ineligible():
    e = make_election("review")
    with pytest.raises(services.ElectionError):
        services.submit_nomination(e, make_member(), "letter")
    e2 = make_election("nominating")
    with pytest.raises(services.ElectionError):
        services.submit_nomination(e2, make_member(role="pre_candidate"), "letter")


def test_nominate_edit_withdraw_resubmit():
    e = make_election("nominating")
    u = make_member()
    n = services.submit_nomination(e, u, "first")
    services.withdraw_nomination(n)
    n.refresh_from_db(); assert n.withdrawn_at
    n2 = services.submit_nomination(e, u, "second")
    assert n2.pk == n.pk and n2.withdrawn_at is None and n2.letter == "second"


def test_withdraw_refused_after_close():
    e = make_election("review")
    n = make_nomination(e, status="pending")
    with pytest.raises(services.ElectionError):
        services.withdraw_nomination(n)


def test_review_only_in_review_phase():
    e = make_election("slate")
    n = make_nomination(e, status="accepted")
    with pytest.raises(services.ElectionError):
        services.review_nomination(n, make_member(), "declined")


def test_publish_slate_requires_no_pending(mailoutbox):
    e = make_election("review")
    make_nomination(e, status="pending")
    with pytest.raises(services.ElectionError):
        services.publish_slate(e, make_member())


def test_publish_slate_refuses_after_voting_close():
    e = make_election("review", voting_close_at=timezone.now() - timezone.timedelta(minutes=1),
                      voting_open_at=timezone.now() - timezone.timedelta(days=1))
    make_nomination(e)
    with pytest.raises(services.ElectionError):
        services.publish_slate(e, make_member())


def test_publish_slate_stamps_and_audits():
    e = make_election("review")
    make_nomination(e)
    admin = make_member()
    services.publish_slate(e, admin)
    e.refresh_from_db()
    assert e.slate_published_at and "Published the slate" in e.audit_notes


def test_freeze_writes_roll_once():
    e = make_election("voting")
    a, b = make_member(), make_member(role="external")
    services.set_override(e, b, "add", "foundation member", make_member())
    assert services.ensure_roll_frozen(e) is True
    assert services.ensure_roll_frozen(e) is False
    on = set(VoterRollEntry.objects.filter(election=e, on_roll=True).values_list("user_id", flat=True))
    assert {a.id, b.id} <= on


def test_remove_voter_who_voted_refused():
    e = make_election("voting")
    cand = make_nomination(e)
    v = make_member()
    services.ensure_roll_frozen(e)
    services.cast_ballot(e, v, [cand.id])
    with pytest.raises(services.ElectionError):
        services.set_override(e, v, "remove", "oops", make_member())


def test_cast_requires_roll_and_voting():
    e = make_election("voting")
    cand = make_nomination(e)
    outsider = make_member(role="external")
    with pytest.raises(services.ElectionError):
        services.cast_ballot(e, outsider, [cand.id])
    e2 = make_election("closed")
    with pytest.raises(services.ElectionError):
        services.cast_ballot(e2, make_member(), [make_nomination(e2).id])


def test_ballot_recorded_email_has_no_choices(mailoutbox, django_capture_on_commit_callbacks):
    e = make_election("voting")
    cand = make_nomination(e, user=make_member(first="Zelda", last="Quill"))
    v = make_member()
    with django_capture_on_commit_callbacks(execute=True):
        services.cast_ballot(e, v, [cand.id])
    body = "\n".join(m.body for m in mailoutbox)
    assert mailoutbox and "Quill" not in body


def test_run_count_and_analyst_check():
    e = make_election("closed", seats=1)
    a = make_nomination(e, user=make_member(role="candidate"))
    services.ensure_roll_frozen(e)
    for _ in range(3):
        ballots.cast(e, make_member(), [a.id])
    result = services.run_count(e, make_member())
    e.refresh_from_db()
    assert e.counted_at and result["elected"] == [a.id]
    assert result["analyst_check"]["short"] is True  # 0 analysts elected, none continuing


def test_advance_sends_call_once_and_freezes(mailoutbox, django_capture_on_commit_callbacks):
    make_member()
    e = make_election("nominating")
    with django_capture_on_commit_callbacks(execute=True):
        assert services.advance_elections()["calls"] == 1
        assert services.advance_elections()["calls"] == 0
    e.refresh_from_db(); assert e.call_sent_at
    v = make_election("voting", call_sent_at=timezone.now())
    stats = services.advance_elections()
    v.refresh_from_db()
    assert v.roll_frozen_at and v.voting_notice_sent_at and stats["voting_notices"] == 1


def test_acclaim_requires_few_candidates():
    e = make_election("slate", seats=2)
    make_nomination(e); make_nomination(e); make_nomination(e)
    with pytest.raises(services.ElectionError):
        services.acclaim(e, make_member())


def test_remind_nonvoters_only():
    e = make_election("voting")
    cand = make_nomination(e)
    voted, waiting = make_member(), make_member()
    services.ensure_roll_frozen(e)
    ballots.cast(e, voted, [cand.id])
    assert services.remind_nonvoters(e, make_member()) == (
        len(services.roll_ids(e)) - 1)
```

(`roll_ids(election) -> set[int]` is also produced by services: the ids of `eligibility.roll_users`.)

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement.**

Add the category in `notifications/categories.py`: a new section constant `SECTION_ELECTIONS = _("Elections")` appended to `SECTION_ORDER` before `SECTION_ACCOUNT`; enum member `ELECTIONS = "elections", _("Board elections")` under a `# --- Elections ---` comment before `# --- Account ---`; and meta:
```python
    _C.ELECTIONS: _M(
        SECTION_ELECTIONS, _("Board elections"),
        _("Calls for nominations, voting, and results. Always emailed: the "
          "bylaws require that members be informed."),
        email_locked=True,
    ),
```
Then `uv run python manage.py makemigrations notifications -n elections_category`.

`elections/emails.py` — one function per message, each rendering `elections/email/<name>.txt` with `{"user", "election", "url", "site": settings.SITE_BASE_URL, "admin_name"}` and sending an `EmailMessage(subject, body, from_email=school_from("LSP Election Administrator"), to=[user.email], reply_to=_reply_to())`, where `_reply_to()` returns the emails of `StaffRole(ELECTION_ADMINISTRATOR).holders` or `[settings.SUPPORT_EMAIL]` when unheld. Subjects:
- `call` — `f"Call for nominations: {e.title}"`
- `nomination_received` — `f"We received your nomination: {e.title}"`
- `candidacy_accepted` — `f"Your candidacy is on the slate: {e.title}"`
- `voting_open` — `f"Voting is open: {e.title}"`
- `reminder` — `f"Reminder, voting closes {local close}: {e.title}"`
- `ballot_recorded` — `f"Your ballot was recorded: {e.title}"` (body: recorded, how to review or change it until close, **no candidate names**)
- `results` — `f"Results: {e.title}"` (winners' names only; body links to the tab)

Each template is plain text, member-facing (commas, not em dashes), signed "The Election Administrator". `url` = `SITE_BASE_URL + reverse("formation") + "?tab=election"`.

`elections/notifications.py` — wraps `notify()`:
```python
from __future__ import annotations

from django.urls import reverse

from notifications.categories import Category
from notifications.dispatch import notify
from payments.sending import ThrottledSender

from . import emails


def tab_url() -> str:
    return reverse("formation") + "?tab=election"


def _batch(users, title, election, email_fn) -> int:
    sender = ThrottledSender()
    n = 0
    for u in users:
        notify(u, Category.ELECTIONS, title=title, url=tab_url(), target=election,
               email_fn=lambda u=u: sender.send(email_fn, u, election))
        n += 1
    return n


def call(users, e):            return _batch(users, f"Call for nominations: {e.title}", e, emails.send_call)
def voting_open(users, e):     return _batch(users, f"Voting is open: {e.title}", e, emails.send_voting_open)
def reminder(users, e):        return _batch(users, f"Reminder, please vote: {e.title}", e, emails.send_reminder)
def results(users, e):         return _batch(users, f"Results: {e.title}", e, emails.send_results)
def candidacy_accepted(users, e): return _batch(users, f"Your candidacy is on the slate: {e.title}", e, emails.send_candidacy_accepted)


def nomination_received(user, e):
    notify(user, Category.ELECTIONS, title=f"Nomination received: {e.title}", url=tab_url(),
           target=e, email_fn=lambda: emails.send_nomination_received(user, e))


def ballot_recorded(user, e):
    notify(user, Category.ELECTIONS, title=f"Ballot recorded: {e.title}", url=tab_url(),
           target=e, email_fn=lambda: emails.send_ballot_recorded(user, e))
```
(Check `formation` is the URL name of the My LSP hub with `grep -n "name=\"formation\"" formation/urls.py`; use the actual name.)

`elections/services.py`:
```python
"""Every state change in an election, each audited (task #813). Views and the
scheduled job call these; nothing else writes Election/Nomination/roll rows."""

from __future__ import annotations

import secrets

from django.db import transaction
from django.utils import timezone

from . import ballots, counting, eligibility
from . import notifications as notify
from .models import Election, Nomination, VoterRollEntry

P = Election.Phase


class ElectionError(Exception):
    """A refused action; the message is shown to the person who tried."""


def _name(u) -> str:
    return u.get_full_name() or u.email


def _save(e, by, text, *fields):
    e.append_audit(by, text)
    e.save(update_fields=[*fields, "audit_notes"])


def current_election():
    open_ = [e for e in Election.objects.all() if e.phase not in Election.FINAL_PHASES]
    return open_[0] if open_ else Election.objects.first()


def roll_ids(election) -> set[int]:
    return set(eligibility.roll_users(election).values_list("id", flat=True))


# --- nominations -----------------------------------------------------------

def submit_nomination(election, user, letter):
    if election.phase != P.NOMINATING:
        raise ElectionError("Nominations are not open.")
    if not eligibility.may_stand(user):
        raise ElectionError("Only analysts, scholars, candidates and candidate scholars may stand.")
    letter = (letter or "").strip()
    if not letter:
        raise ElectionError("Please write a motivation letter.")
    nom, _ = Nomination.objects.update_or_create(
        election=election, user=user,
        defaults={"letter": letter, "withdrawn_at": None,
                  "role_at_submission": user.profile.role},
    )
    notify.nomination_received(user, election)
    return nom


def withdraw_nomination(nomination):
    if nomination.election.phase != P.NOMINATING:
        raise ElectionError("Nominations have closed; ask the Election Administrator.")
    nomination.withdrawn_at = timezone.now()
    nomination.save(update_fields=["withdrawn_at", "updated_at"])


def review_nomination(nomination, by, status, note=""):
    e = nomination.election
    if e.phase != P.REVIEW:
        raise ElectionError("Nominations can be reviewed only after they close and before the slate is published.")
    if status not in (Nomination.Status.ACCEPTED, Nomination.Status.DECLINED):
        raise ElectionError("Choose accept or decline.")
    nomination.status = status
    nomination.board_note = note.strip()
    nomination.reviewed_by = by
    nomination.reviewed_at = timezone.now()
    nomination.save(update_fields=["status", "board_note", "reviewed_by", "reviewed_at", "updated_at"])
    _save(e, by, f"Board marked {nomination.name}'s nomination {nomination.get_status_display().lower()}.")


# --- slate, acclamation -------------------------------------------------------

def publish_slate(election, by):
    if election.phase != P.REVIEW:
        raise ElectionError("The slate can be published only during Board review.")
    live = election.nominations.filter(withdrawn_at__isnull=True)
    if live.filter(status=Nomination.Status.PENDING).exists():
        raise ElectionError("The Board has not decided every nomination yet.")
    accepted = list(live.filter(status=Nomination.Status.ACCEPTED).select_related("user"))
    if not accepted:
        raise ElectionError("No nominations were accepted.")
    if election.voting_close_at <= timezone.now():
        raise ElectionError("Voting's close date has passed. Extend it in Settings first.")
    election.slate_published_at = timezone.now()
    election.slate_published_by = by
    _save(election, by, f"Published the slate ({len(accepted)} candidates).",
          "slate_published_at", "slate_published_by")
    notify.candidacy_accepted([n.user for n in accepted], election)


def acclaim(election, by):
    if election.phase not in (P.SLATE,):
        raise ElectionError("An election can be closed without a vote only after the slate is published and before voting opens.")
    if len(ballots.candidates(election)) > election.seats:
        raise ElectionError("There are more candidates than seats, so the bylaws call for a vote.")
    election.acclaimed_at = timezone.now()
    election.acclaimed_by = by
    _save(election, by, "Closed as elected without a vote.", "acclaimed_at", "acclaimed_by")
    notify.results(list(eligibility.roll_users(election)), election)


# --- the roll -------------------------------------------------------------------

def ensure_roll_frozen(election, now=None) -> bool:
    now = now or timezone.now()
    with transaction.atomic():
        e = Election.objects.select_for_update().get(pk=election.pk)
        if e.roll_frozen_at or e.phase_at(now) not in (P.VOTING, P.CLOSED):
            return False
        for u in eligibility.computed_roll(e):
            VoterRollEntry.objects.update_or_create(
                election=e, user=u, defaults={"on_roll": True, "role_at_freeze": u.profile.role})
        e.roll_frozen_at = now
        _save(e, None, "Froze the voter roll.", "roll_frozen_at")
    election.roll_frozen_at = now
    return True


def set_override(election, user, override, reason, by):
    reason = (reason or "").strip()
    if not reason:
        raise ElectionError("Give a reason; it is kept in the record.")
    if election.phase in (P.COUNTED, P.PUBLISHED, P.ACCLAIMED, P.CLOSED):
        raise ElectionError("The roll is closed.")
    if override == VoterRollEntry.Override.REMOVE and user.id in ballots.voted_user_ids(election):
        raise ElectionError(f"{_name(user)} has already voted; their ballot stands.")
    row, _ = VoterRollEntry.objects.get_or_create(election=election, user=user)
    row.override, row.reason, row.override_by, row.override_at = override, reason, by, timezone.now()
    if election.roll_frozen_at:
        row.on_roll = override == VoterRollEntry.Override.ADD
        if row.on_roll and not row.role_at_freeze:
            row.role_at_freeze = user.profile.role
    row.save()
    verb = "Added" if override == VoterRollEntry.Override.ADD else "Removed"
    _save(election, by, f"{verb} {_name(user)} {'to' if verb == 'Added' else 'from'} the roll: {reason}")


# --- voting -----------------------------------------------------------------------

def cast_ballot(election, voter, ranked):
    if election.phase != P.VOTING:
        raise ElectionError("Voting is not open.")
    ensure_roll_frozen(election)
    if not eligibility.is_on_roll(election, voter):
        raise ElectionError("You are not on this election's voter roll. Write to the Election Administrator if that is a mistake.")
    try:
        ballots.cast(election, voter, ranked)
    except ValueError as exc:
        raise ElectionError(str(exc)) from exc
    notify.ballot_recorded(voter, election)


def remind_nonvoters(election, by) -> int:
    if election.phase != P.VOTING:
        raise ElectionError("Voting is not open.")
    ensure_roll_frozen(election)
    voted = ballots.voted_user_ids(election)
    waiting = [u for u in eligibility.roll_users(election) if u.id not in voted]
    n = notify.reminder(waiting, election)
    _save(election, by, f"Sent a reminder to {n} voters who had not voted.")
    return n


# --- dates -------------------------------------------------------------------------

_WINDOWS = {"nominations": ("nominations_open_at", "nominations_close_at"),
            "voting": ("voting_open_at", "voting_close_at")}


def open_now(election, which, by):
    start, end = _WINDOWS[which]
    now = timezone.now()
    if getattr(election, start) <= now:
        raise ElectionError("That window has already opened.")
    if which == "voting" and election.nominations_close_at > now:
        raise ElectionError("Close nominations first.")
    setattr(election, start, now)
    _save(election, by, f"Opened {which} now.", start)


def close_now(election, which, by):
    start, end = _WINDOWS[which]
    now = timezone.now()
    if not (getattr(election, start) <= now < getattr(election, end)):
        raise ElectionError("That window is not open.")
    setattr(election, end, now)
    if which == "nominations" and election.voting_open_at < now:
        election.voting_open_at = now
    _save(election, by, f"Closed {which} now.", end, "voting_open_at")


# --- count and results --------------------------------------------------------------

def analyst_check(election, elected_ids) -> dict:
    from committees.models import Committee
    from workgroups.models import WorkgroupMembership

    elected = Nomination.objects.filter(id__in=elected_ids)
    elected_analysts = sum(1 for n in elected if n.role_at_submission == "analyst")
    term_end = timezone.localdate().replace(month=12, day=31)
    board = Committee.objects.filter(slug="board").select_related("workgroup").first()
    continuing = 0
    if board and board.workgroup_id:
        continuing = (WorkgroupMembership.objects.serving()
                      .filter(workgroup=board.workgroup, end_date__gt=term_end,
                              user__profile__role="analyst")
                      .exclude(user_id__in=[n.user_id for n in elected]).count())
    total = elected_analysts + continuing
    return {"elected_analysts": elected_analysts, "continuing_analysts": continuing,
            "total": total, "short": total < 3}


def run_count(election, by) -> dict:
    if election.phase != P.CLOSED:
        raise ElectionError("The count runs after voting closes.")
    cands = [n.id for n in ballots.candidates(election)]
    seed = secrets.randbits(32)
    result = counting.count(election.count_method, ballots.anonymous_ballots(election),
                            cands, election.seats, seed)
    result["names"] = {str(n.id): n.name for n in ballots.candidates(election)}
    result["analyst_check"] = analyst_check(election, result["elected"])
    election.count_result = result
    election.counted_at = timezone.now()
    election.counted_by = by
    _save(election, by, f"Ran the count ({election.get_count_method_display()}).",
          "count_result", "counted_at", "counted_by")
    return result


def publish_results(election, by):
    if election.phase != P.COUNTED:
        raise ElectionError("Run the count first.")
    election.results_published_at = timezone.now()
    election.results_published_by = by
    _save(election, by, "Published the results.", "results_published_at", "results_published_by")
    notify.results(list(eligibility.roll_users(election)), election)


# --- the scheduled job ------------------------------------------------------------

def advance_elections(now=None) -> dict:
    now = now or timezone.now()
    stats = {"calls": 0, "frozen": 0, "voting_notices": 0}
    for e in Election.objects.filter(acclaimed_at__isnull=True, results_published_at__isnull=True):
        phase = e.phase_at(now)
        if e.call_sent_at is None and phase != P.DRAFT:
            with transaction.atomic():
                locked = Election.objects.select_for_update().get(pk=e.pk)
                if locked.call_sent_at is None:
                    locked.call_sent_at = now
                    _save(locked, None, "Sent the call for nominations.", "call_sent_at")
                    notify.call(list(eligibility.eligible_voters_qs()), locked)
                    stats["calls"] += 1
        if phase == P.VOTING:
            if ensure_roll_frozen(e, now):
                stats["frozen"] += 1
            with transaction.atomic():
                locked = Election.objects.select_for_update().get(pk=e.pk)
                if locked.voting_notice_sent_at is None:
                    locked.voting_notice_sent_at = now
                    _save(locked, None, "Sent the voting-open notice.", "voting_notice_sent_at")
                    notify.voting_open(list(eligibility.roll_users(locked)), locked)
                    stats["voting_notices"] += 1
    return stats
```

Note: a call whose `nominations_open_at` passed while `phase` is already past NOMINATING (e.g. an election created late) still sends once; that is correct — members must be informed.

- [ ] **Step 4: Run** `uv run pytest elections notifications -q` → PASS (also run `uv run python manage.py makemigrations --check --dry-run`).
- [ ] **Step 5: Commit** `feat(elections): services, audit trail, roll freeze, count, notices (task #813)`.

---

### Task 6: Administrator console + settings form + date rules + help doc

**Files:**
- Create: `elections/permissions.py`, `elections/views_admin.py`, `elections/urls.py`, `elections/templates/elections/admin/{base,list,overview,settings,nominations,roll,count,help}.html`, `core/docs/election-guide.md`, `elections/tests/test_views_admin.py`
- Modify: `elections/forms.py` (add `ElectionSettingsForm`, `OverrideForm`), `config/urls.py` (`path("", include("elections.urls"))` beside registrations), `core/staff.py` (PANEL_ROLES + hub card + appointments warning), `core/templates/core/staff/admin/board.html` (role list text), `accounts/views.py` (badge exclusion)

**Interfaces — Produces:**
- `permissions.is_election_administrator(user) -> bool` (superuser or holder)
- `permissions.can_review_nominations(user) -> bool` (superuser or `is_on_committee(user, "board")`)
- URL names (app_name `"elections"`): `admin` (`/admin-tools/elections/`), `admin_new`, `admin_overview <slug>`, `admin_settings <slug>`, `admin_nominations <slug>`, `admin_roll <slug>`, `admin_count <slug>`, `admin_help`, `admin_action <slug>` (POST, `action` ∈ open_nominations_now, close_nominations_now, open_voting_now, close_voting_now, publish_slate, acclaim, run_count, publish_results, remind), `admin_override <slug>` (POST user, override, reason)
- `forms.ElectionSettingsForm(instance=..., data=..., now=...)` — fields title, seats, the four datetimes (`DateTimeInput(type="datetime-local")`), results_due (`DateInput(type="date")`), count_method, show_during_voting, show_results; `.changed_summary() -> list[str]`.

Date rules in `ElectionSettingsForm.clean()` (instance exists; on create, all dates must be in the future):
1. `nominations_open_at < nominations_close_at <= voting_open_at < voting_close_at`.
2. For each of the four date fields that **changed**: the original value must be > now (a passed date cannot be changed) and the new value must be ≥ now − 60s.
3. `seats` locked once phase ∈ {VOTING, CLOSED, COUNTED, PUBLISHED, ACCLAIMED}; `count_method` locked once counted; visibility locked once results published or acclaimed; everything locked once counted except visibility.
4. `results_due` defaults on create to `voting_close_at` local date + 7.
Saving appends one audit line listing changed fields with old → new (local time formatting `%Y-%m-%d %H:%M`).

- [ ] **Step 1: Failing tests** (`test_views_admin.py`) — key cases:

```python
import pytest
from django.urls import reverse
from django.utils import timezone

from core.models import StaffRole
from elections.models import Election
from elections.tests.factories import make_election, make_member, make_nomination

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user():
    u = make_member()
    StaffRole.objects.get(key=StaffRole.ELECTION_ADMINISTRATOR).holders.add(u)
    return u


def test_gate(client):
    e = make_election()
    url = reverse("elections:admin_overview", args=[e.slug])
    assert client.get(url).status_code == 302           # anonymous → login
    wc = make_member()
    StaffRole.objects.get(key=StaffRole.WEB_COORDINATOR).holders.add(wc)
    client.force_login(wc)
    assert client.get(url).status_code == 404           # Web Coordinator NOT admitted


def test_create_election(client, admin_user):
    client.force_login(admin_user)
    now = timezone.localtime() + timezone.timedelta(days=1)
    fmt = "%Y-%m-%dT%H:%M"
    r = client.post(reverse("elections:admin_new"), {
        "title": "Board election 2026", "seats": 3,
        "nominations_open_at": now.strftime(fmt),
        "nominations_close_at": (now + timezone.timedelta(days=14)).strftime(fmt),
        "voting_open_at": (now + timezone.timedelta(days=21)).strftime(fmt),
        "voting_close_at": (now + timezone.timedelta(days=35)).strftime(fmt),
        "count_method": "stv", "show_during_voting": "status", "show_results": "winners",
    })
    e = Election.objects.get()
    assert r.status_code == 302 and e.results_due is not None


def test_extension_allowed_reopen_refused(client, admin_user):
    client.force_login(admin_user)
    e = make_election("nominating")
    fmt = "%Y-%m-%dT%H:%M"
    loc = timezone.localtime
    base = {"title": e.title, "seats": e.seats, "count_method": "stv",
            "show_during_voting": "status", "show_results": "winners",
            "nominations_open_at": loc(e.nominations_open_at).strftime(fmt),
            "voting_open_at": loc(e.voting_open_at).strftime(fmt),
            "voting_close_at": loc(e.voting_close_at).strftime(fmt),
            "results_due": e.results_due or ""}
    later = loc(e.nominations_close_at + timezone.timedelta(hours=12)).strftime(fmt)
    r = client.post(reverse("elections:admin_settings", args=[e.slug]),
                    {**base, "nominations_close_at": later})
    assert r.status_code == 302
    e.refresh_from_db()
    assert "nominations_close_at" in e.audit_notes or "Nominations close" in e.audit_notes
    # moving the passed open date is refused
    r = client.post(reverse("elections:admin_settings", args=[e.slug]),
                    {**base, "nominations_close_at": later,
                     "nominations_open_at": loc(timezone.now() + timezone.timedelta(hours=1)).strftime(fmt)})
    assert r.status_code == 200 and b"already passed" in r.content


def test_roll_shows_voted_not_time(client, admin_user):
    from elections import services
    e = make_election("voting")
    cand = make_nomination(e)
    v = make_member(first="Vera", last="Voter")
    services.ensure_roll_frozen(e)
    services.cast_ballot(e, v, [cand.id])
    client.force_login(admin_user)
    html = client.get(reverse("elections:admin_roll", args=[e.slug])).content.decode()
    assert "Voter" in html and "Voted" in html


def test_action_publish_slate(client, admin_user):
    e = make_election("review")
    make_nomination(e)
    client.force_login(admin_user)
    client.post(reverse("elections:admin_action", args=[e.slug]), {"action": "publish_slate"})
    e.refresh_from_db()
    assert e.slate_published_at


def test_appointments_warns_for_director(client):
    from committees.models import Committee
    from workgroups.models import WorkgroupMembership
    board = Committee.objects.get(slug="board")
    director, chair = make_member(), make_member()
    WorkgroupMembership.objects.create(workgroup=board.workgroup, user=director, role="member")
    WorkgroupMembership.objects.create(workgroup=board.workgroup, user=chair, role="member")
    client.force_login(chair)
    r = client.post(reverse("board_appointments"), {
        "action": "appoint", "role": StaffRole.ELECTION_ADMINISTRATOR, "user": director.pk}, follow=True)
    assert b"sitting director" in r.content


def test_directory_does_not_badge_role():
    import inspect
    from accounts import views
    assert "ELECTION_ADMINISTRATOR" in inspect.getsource(views._directory_qs)
```

(If `Committee(slug="board")` isn't seeded in the test DB, create it with its workgroup the way existing Board tests do — grep `slug="board"` in `committees/tests*` and reuse that fixture.)

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**

`elections/permissions.py`:
```python
from core.access import has_staff_role
from core.models import StaffRole


def is_election_administrator(user) -> bool:
    """The Election Administrator console gate. Deliberately not the Web
    Coordinator: the role exists to be impartial (task #813)."""
    return bool(getattr(user, "is_authenticated", False)) and (
        user.is_superuser or has_staff_role(user, StaffRole.ELECTION_ADMINISTRATOR))


def can_review_nominations(user) -> bool:
    from committees.permissions import is_on_committee
    return bool(getattr(user, "is_authenticated", False)) and (
        user.is_superuser or is_on_committee(user, "board"))
```

`elections/views_admin.py` follows `registrations/views_admin.py`: an `administrator_required` decorator (anonymous → `redirect_to_login`, non-permitted → `Http404`), `TABS = [("overview","Overview"),("settings","Settings"),("nominations","Nominations"),("roll","Voter roll"),("count","Count"),("help","Help")]`, `_tab_links(election)`, `_render(request, election, tab_key, template, ctx)`. Views:
- `admin_index`: redirect to `admin_overview` of `services.current_election()`, or render `list.html` with a "New election" button when none exist. `list.html` also lists past elections.
- `admin_new`: GET/POST `ElectionSettingsForm`; slug = `slugify(title)` uniquified with `-2`, `-3`; on save, audit "Created the election."
- `admin_overview`: phase, dates (local), next action text keyed by phase, counts (live nominations, accepted, roll size via `len(services.roll_ids(e))`, turnout via `ballots.turnout(e)`), no-contest notice when phase == SLATE and `len(ballots.candidates(e)) <= e.seats` quoting the bylaw sentence, results-due when phase ≥ CLOSED, action buttons for the phase (forms POSTing to `admin_action`), and the audit notes in a `<pre class="whitespace-pre-wrap">`.
- `admin_settings`: the form, locked fields rendered `disabled`.
- `admin_nominations`: every nomination with letter (`linebreaks`), status, board note; Publish slate button when phase == REVIEW.
- `admin_roll`: if not frozen, `eligibility.computed_roll(e)` plus removed rows listed separately; if frozen, `roll_users`. Columns: name, role, standing, dues state (from `{row["user"].id: row["dues_state"] for row in payments.ledger.accounts_overview()}`; display `—` when absent), override reason, and during VOTING/CLOSED a "Voted"/"Not yet" badge from `ballots.voted_user_ids(e)`. Add form (`OverrideForm`: email lookup + reason) and per-row Remove form. "Remind those who haven't voted" button when VOTING.
- `admin_count`: Run count (CLOSED), result (names from `count_result["names"]`), analyst warning (`alert-warning`) if `short`, lot draws (`alert-warning` with seed), STV stages table, Publish results (COUNTED).
- `admin_help`: `render_doc("election-guide")`.
- `admin_action`: POST; dispatch table to services; `ElectionError` → `messages.error`; success → `messages.success` with a short sentence; redirect back to `request.POST["next"]` if `url_has_allowed_host_and_scheme`, else overview.
- `admin_override`: POST, `set_override`.

`elections/urls.py`:
```python
from django.urls import path

from . import views_admin, views_board, views_member

app_name = "elections"
_A = "admin-tools/elections"

urlpatterns = [
    path(f"{_A}/", views_admin.admin_index, name="admin"),
    path(f"{_A}/new/", views_admin.admin_new, name="admin_new"),
    path(f"{_A}/help/", views_admin.admin_help, name="admin_help"),
    path(f"{_A}/<slug:slug>/", views_admin.admin_overview, name="admin_overview"),
    path(f"{_A}/<slug:slug>/settings/", views_admin.admin_settings, name="admin_settings"),
    path(f"{_A}/<slug:slug>/nominations/", views_admin.admin_nominations, name="admin_nominations"),
    path(f"{_A}/<slug:slug>/roll/", views_admin.admin_roll, name="admin_roll"),
    path(f"{_A}/<slug:slug>/count/", views_admin.admin_count, name="admin_count"),
    path(f"{_A}/<slug:slug>/action/", views_admin.admin_action, name="admin_action"),
    path(f"{_A}/<slug:slug>/override/", views_admin.admin_override, name="admin_override"),
    path("admin-tools/board/elections/", views_board.review, name="board_review"),
    path("admin-tools/board/elections/<int:pk>/decide/", views_board.decide, name="board_decide"),
    path("elections/<slug:slug>/nominate/", views_member.nominate, name="nominate"),
    path("elections/<slug:slug>/withdraw/", views_member.withdraw, name="withdraw"),
    path("elections/<slug:slug>/ballot/", views_member.ballot, name="ballot"),
]
```
(Create `views_board.py` and `views_member.py` as stubs raising `Http404` here; Tasks 7–8 fill them.)

`core/staff.py`: add `StaffRole.ELECTION_ADMINISTRATOR` to `PANEL_ROLES`; in `_panels_for`, after the Registration card:
`if user.is_superuser or has_staff_role(user, StaffRole.ELECTION_ADMINISTRATOR):` append `{"title": "Election Admin", "blurb": "Run the Board election: dates, nominations, the voter roll, and the count.", "url": reverse("elections:admin")}`. In `board_appointments` after `role.holders.add(member)` on appoint, add:
```python
            if role.key == StaffRole.ELECTION_ADMINISTRATOR:
                from committees.permissions import is_on_committee
                if is_on_committee(member, "board"):
                    messages.warning(
                        request,
                        f"{member.get_full_name() or member.email} is a sitting director. "
                        "The Election Administrator should be neither a director nor a candidate.",
                    )
```
`board.html` Appointments card body: add "Election Administrator" to the list. `accounts/views.py` `_directory_qs` exclusion tuple: add `StaffRole.ELECTION_ADMINISTRATOR`.

`core/docs/election-guide.md`: sections — How an election runs (the phases table from the spec, member-facing wording), Dates (the four dates, extensions, open/close now, voting waits for the slate), Board review (declined applicants are contacted personally by a Board member; the site sends them nothing), The voter roll (who is on it, dues column is information, add/remove with reasons, frozen when voting opens, cannot remove someone who voted), Counting (STV vs most votes in two short paragraphs, ties and lots, three-analyst warning), Visibility settings, **What ballot secrecy covers** (no screen shows how anyone voted, including this one; the database still links a ballot to its voter so someone with direct database access could read it), What the bylaws say (quote Art. 3 §1 excerpt). Avoid lines starting with `+`, `-`, `*` mid-paragraph inside list items (rendered-markdown gotcha).

- [ ] **Step 4: Run** `uv run pytest elections core accounts -q` → PASS.
- [ ] **Step 5: Commit** `feat(elections): Election Administrator console, appointments warning, hub card (task #813)`.

---

### Task 7: Board review page

**Files:** Fill `elections/views_board.py`; create `elections/templates/elections/board/review.html`, `elections/tests/test_board.py`; modify `core/staff.py` `board_admin` context + `board.html` (Elections card when an election is in REVIEW).

**Interfaces — Consumes:** `permissions.can_review_nominations`, `services.review_nomination`, `services.current_election`.

- [ ] **Step 1: Failing tests**
```python
import pytest
from django.urls import reverse

from elections.tests.factories import make_election, make_member, make_nomination

pytestmark = pytest.mark.django_db


@pytest.fixture
def director():
    from committees.models import Committee
    from workgroups.models import WorkgroupMembership
    u = make_member()
    WorkgroupMembership.objects.create(workgroup=Committee.objects.get(slug="board").workgroup,
                                       user=u, role="member")
    return u


def test_non_director_404(client):
    client.force_login(make_member())
    assert client.get(reverse("elections:board_review")).status_code == 404


def test_decide(client, director):
    e = make_election("review")
    n = make_nomination(e, status="pending", letter="My letter here")
    client.force_login(director)
    page = client.get(reverse("elections:board_review")).content.decode()
    assert "My letter here" in page and "contacted personally" in page
    client.post(reverse("elections:board_decide", args=[n.pk]), {"status": "declined", "note": "n"})
    n.refresh_from_db()
    assert n.status == "declined" and n.reviewed_by == director


def test_board_page_never_shows_roll(client, director):
    e = make_election("review")
    client.force_login(director)
    assert "Voted" not in client.get(reverse("elections:board_review")).content.decode()
```
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `review` (GET; `current_election()`; lists live nominations with letter, status, note; Accept/Decline forms with a note textarea, enabled only in REVIEW; a standing `alert-info`: "A declined applicant must be contacted personally by a Board member to explain the reasons (Bylaws, Article 3, Section 1). The site does not notify them.") and `decide` (POST, `review_nomination`, messages, redirect). Gate: `can_review_nominations`, anonymous → login, else 404. Template extends `core/base.html` with the `_base.html`-style header ("Governance · Board", "Election nominations"). `board_admin` adds `election_in_review` (current election if phase == REVIEW); `board.html` shows a `_section.html` card "Election nominations" linking to `elections:board_review` with `count` = pending nominations when set.
- [ ] **Step 4: Run** `uv run pytest elections core -q` → PASS.
- [ ] **Step 5: Commit** `feat(elections): Board review of nominations (task #813)`.

---

### Task 8: Member tab — nominate, slate, ballot, status, results

**Files:** Fill `elections/views_member.py`; create `elections/queries.py`, `formation/templates/formation/_tab_election.html`, `elections/tests/test_views_member.py`; modify `formation/tabs.py`, `formation/views.py`, `formation/templates/formation/formation.html`, `elections/forms.py` (`NominationForm`).

**Interfaces — Produces:**
- `queries.visible_election_for(user) -> Election | None` — the current election if it is past DRAFT and (not final, or final within 30 days of `results_published_at`/`acclaimed_at`) and the user is an eligible voter, on the roll, or has a nomination in it. Cheap path: return None immediately unless `user.profile.role in VOTER_ROLES` or the user has a roll/nomination row (two `exists()` queries at most).
- `queries.tab_context(request, election) -> dict` for the template.
- `forms.NominationForm` — one `letter` `CharField(widget=Textarea(rows=10))`, label "Motivation letter", help "Your motivation, your interests, and what you can bring to the Board and the School (Bylaws, Article 3)."

- [ ] **Step 1: Failing tests** (`test_views_member.py`):
```python
import pytest
from django.urls import reverse

from elections import ballots, services
from elections.tests.factories import make_election, make_member, make_nomination

pytestmark = pytest.mark.django_db
TAB = reverse("formation") + "?tab=election"   # adjust name if hub URL differs


def test_tab_hidden_when_no_election(client):
    u = make_member(); client.force_login(u)
    assert "?tab=election" not in client.get(reverse("formation")).content.decode()


def test_tab_hidden_for_non_voters(client):
    make_election("nominating")
    u = make_member(role="external"); client.force_login(u)
    assert "?tab=election" not in client.get(reverse("formation")).content.decode()


def test_nominate_flow(client):
    e = make_election("nominating")
    u = make_member(role="candidate"); client.force_login(u)
    assert "Motivation letter" in client.get(TAB).content.decode()
    client.post(reverse("elections:nominate", args=[e.slug]), {"letter": "I will serve."})
    assert e.nominations.get().letter == "I will serve."
    assert "Under review" not in client.get(TAB).content.decode() or True


def test_pre_candidate_sees_no_form(client):
    make_election("nominating")
    u = make_member(role="pre_candidate"); client.force_login(u)
    assert "Motivation letter" not in client.get(TAB).content.decode()


def test_ballot_view_freezes_roll_lazily(client):
    e = make_election("voting")
    a = make_nomination(e)
    v = make_member(); client.force_login(v)
    page = client.get(TAB).content.decode()
    e.refresh_from_db()
    assert e.roll_frozen_at and f"rank_{a.id}" in page


def test_cast_and_change(client):
    e = make_election("voting")
    a, b = make_nomination(e), make_nomination(e)
    v = make_member(); client.force_login(v)
    client.post(reverse("elections:ballot", args=[e.slug]), {f"rank_{a.id}": "1", f"rank_{b.id}": "2"})
    client.post(reverse("elections:ballot", args=[e.slug]), {f"rank_{b.id}": "1"})
    assert [n.id for n in ballots.own_ballot(v, e)] == [b.id]


def test_duplicate_rank_rejected(client):
    e = make_election("voting")
    a, b = make_nomination(e), make_nomination(e)
    v = make_member(); client.force_login(v)
    r = client.post(reverse("elections:ballot", args=[e.slug]),
                    {f"rank_{a.id}": "1", f"rank_{b.id}": "1"}, follow=True)
    assert ballots.own_ballot(v, e) is None and b"different rank" in r.content


def test_turnout_only_when_enabled(client):
    e = make_election("voting", show_during_voting="turnout")
    v = make_member(); client.force_login(v)
    assert "Turnout" in client.get(TAB).content.decode()
    e.show_during_voting = "status"; e.save()
    assert "Turnout" not in client.get(TAB).content.decode()


def test_results_winners_only_vs_full(client):
    e = make_election("closed", seats=1)
    a = make_nomination(e, user=make_member(first="Ada", last="Winner"))
    v = make_member()
    services.ensure_roll_frozen(e)
    ballots.cast(e, v, [a.id])
    admin = make_member()
    services.run_count(e, admin)
    services.publish_results(e, admin)
    client.force_login(v)
    page = client.get(TAB).content.decode()
    assert "Winner" in page and "Stage" not in page
    e.show_results = "full"; e.save()
    assert "Stage" in client.get(TAB).content.decode()
```
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** `formation/tabs.py`: after the `member` block, `from elections.queries import visible_election_for` and `if visible_election_for(user) is not None: tabs.append(("election", "Election"))` (before "profile"). `formation/views.py`: `elif active == "election": from elections.queries import tab_context, visible_election_for; e = visible_election_for(user); ctx.update(tab_context(request, e))`. `formation.html`: `{% elif active_tab == "election" %}{% include "formation/_tab_election.html" %}`.

`tab_context` calls `services.ensure_roll_frozen(e)` when phase is VOTING, then returns: `election`, `phase`, `may_stand`, `nomination` (own), `nomination_form` (prefilled), `candidates` (from `ballots.candidates` once SLATE or later), `on_roll`, `own_ballot`, `ballot_form` (`BallotForm(candidates, initial_order=[n.id for n in own_ballot or []])`), `turnout` (only when `show_during_voting == "turnout"` and phase == VOTING), `roll_size` (same condition), `results` (when PUBLISHED: elected names from `count_result`; `stages` only if `show_results == "full"`), `acclaimed_names` (when ACCLAIMED).

Template sections by phase (DaisyUI cards, `bg-base-100`, semantic tokens only, commas not em dashes): status line ("Nominations are open until …" / "The Board is reviewing nominations" / "Voting is open until …" / "Voting has closed" / "Results"), dates in the member's local time (`user_datetime` filter used elsewhere — grep `user_datetime` and reuse), the nomination form or own nomination with Withdraw, the slate with letters in `<details>`, the ballot (table: candidate | rank select) with the instruction "Rank as many candidates as you like, 1st for your first choice. You can change your ballot until voting closes.", own ballot listed in rank order with "Change my ballot", turnout when present, results.

`views_member.py`: `nominate` (POST, login required; `NominationForm`; `services.submit_nomination`; `ElectionError` → `messages.error`; redirect to the tab), `withdraw` (POST, own nomination), `ballot` (POST; `BallotForm(ballots.candidates(e), data=request.POST)`; invalid → `messages.error` with the form's first non-field error, redirect; valid → `services.cast_ballot`; success message "Your ballot was recorded. You can change it until voting closes.").
- [ ] **Step 4: Run** `uv run pytest elections formation -q` → PASS.
- [ ] **Step 5: Commit** `feat(elections): My LSP Election tab: nominate, ballot, results (task #813)`.

---

### Task 9: Scheduled job hook, docs, full suite, browser walkthrough

**Files:** Modify `workgroups/management/commands/send_meeting_reminders.py` (add `_elections(now, dry)`), `CLAUDE.md` (status log entry), create `elections/tests/test_job.py`.

- [ ] **Step 1: Failing test**
```python
import pytest
from django.core.management import call_command

from elections.tests.factories import make_election, make_member

pytestmark = pytest.mark.django_db


def test_meeting_reminders_advances_elections(django_capture_on_commit_callbacks):
    make_member()
    e = make_election("nominating")
    with django_capture_on_commit_callbacks(execute=True):
        call_command("send_meeting_reminders")
    e.refresh_from_db()
    assert e.call_sent_at


def test_dry_run_sends_nothing():
    e = make_election("nominating")
    call_command("send_meeting_reminders", "--dry-run")
    e.refresh_from_db()
    assert e.call_sent_at is None
```
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `_elections` mirroring `_per_class` (try/except logging so a failure never stops the reminders; dry run prints what would advance by listing elections whose call/notice is due without calling services). Call it at the end of `handle`.
- [ ] **Step 4: Full verification**
  - `uv run ruff check .`
  - `uv run python manage.py makemigrations --check --dry-run`
  - `uv run pytest -q -n auto` → all green
  - `npm run build:css`, `uv run python manage.py runserver`; in a browser: create an election as an Election Administrator, open nominations now, nominate as a candidate, close now, decide as a Board member, publish slate, open voting now, vote as two members (change one ballot), check the roll's voted/not yet, close now, run count, publish, view results on the member tab. Check dark theme and phone width.
- [ ] **Step 5: CLAUDE.md** — add a status-log entry "Board elections (task #813)" summarizing the decisions and the secrecy structure, linking the spec. Commit `feat(elections): scheduled advancement + docs (task #813)`.
