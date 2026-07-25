"""'My Groups' — a member's current and former groups of every kind.

Brings together the three distinct ways a person belongs to a
:class:`~workgroups.models.Workgroup`:

* **stored roster rows** — cartels, committees, working groups, seminar
  faculty … (a :class:`WorkgroupMembership`);
* **role-derived membership** — ``auto_member_role`` (e.g. every Analyst is in
  the Meeting of Analysts), which has no stored row; and
* **term registrations** — seminar / reading-group students, who are *never*
  stored as roster rows; their membership flows from a paid/comped
  :class:`~registrations.models.Registration` on the current term.

Current-vs-former is decided by the authoritative
:meth:`Workgroup.is_member` / :meth:`Workgroup.has_archive_access` predicates,
so this page can never drift from the access checks the rest of the site
enforces.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from registrations.models import Registration

from .models import Workgroup, WorkgroupMembership


@dataclass
class MyGroup:
    """One group the user is in or has been in, with the user's standing."""

    workgroup: Workgroup
    role_label: str
    is_lead: bool
    is_current: bool
    ended_on: datetime.date | None  # the user's stored term end, if it ended
    archived: bool                  # the group itself was dissolved
    via_registration: bool          # membership comes from a term registration

    @property
    def name(self) -> str:
        return self.workgroup.name

    @property
    def url(self) -> str:
        return self.workgroup.get_absolute_url()

    @property
    def kind(self) -> str:
        return self.workgroup.kind

    @property
    def academic_year(self):
        return self.workgroup.program_academic_year()

    @property
    def status_note(self) -> str | None:
        """A short past-tense note for former groups; ``None`` while current."""
        if self.is_current:
            return None
        if self.archived:
            return "Archived"
        if self.via_registration:
            return "Past term"
        if self.ended_on:
            return f"Until {self.ended_on:%b %Y}"
        return "Past"


@dataclass
class MyEvent:
    """A standalone event the user is registered for that isn't represented by
    one of their groups — a Day of Assembly, Working Day, special event, etc."""

    event: object         # events.models.Event
    registration: object  # the user's registrations.models.Registration
    status: str           # the registration status (paid / comped / awaiting)
    is_upcoming: bool

    @property
    def title(self) -> str:
        return self.event.title

    @property
    def url(self) -> str:
        from django.urls import reverse

        return reverse("events:detail", args=[self.event.slug])

    @property
    def type_label(self) -> str:
        return self.event.get_event_type_display()

    @property
    def academic_year(self) -> str:
        return self.event.academic_year

    @property
    def is_comped(self) -> bool:
        return self.status == Registration.Status.COMPED

    @property
    def needs_payment(self) -> bool:
        """The registration is approved/awaiting and still owes money — worth a
        nudge with a link to finish checkout."""
        return self.registration.needs_payment

    @property
    def pay_url(self) -> str:
        """The confirmation page, where an awaiting registration can resume
        Stripe Checkout (or be cancelled)."""
        from django.urls import reverse

        return reverse("registrations:confirm", args=[self.registration.id])


def _better_membership(
    a: WorkgroupMembership, b: WorkgroupMembership
) -> WorkgroupMembership:
    """The membership row that best represents the user's standing in a group:
    a currently-serving row beats an ended one; otherwise the later one wins."""
    a_serving = a.end_date is None
    b_serving = b.end_date is None
    if a_serving != b_serving:
        return a if a_serving else b
    a_key = a.start_date or a.end_date
    b_key = b.start_date or b.end_date
    if a_key is None:
        return b
    if b_key is None:
        return a
    return a if a_key >= b_key else b


def my_groups(user) -> list[MyGroup]:
    """Every group ``user`` is in or has ever been in, across all kinds.

    Returns an unsorted list of :class:`MyGroup`; the view splits it into
    current / past and buckets by kind for display.
    """
    if not getattr(user, "is_authenticated", False):
        return []

    # workgroup_id -> the best stored membership row to display (prefer a
    # currently-serving one, else the most recently ended).
    stored: dict[int, WorkgroupMembership] = {}
    for m in (
        WorkgroupMembership.objects
        .filter(user=user)
        # ``workgroup__committee`` so ``role_label`` resolves officer titles
        # (Board Chair → President) without a per-row query.
        .select_related("workgroup", "workgroup__committee")
    ):
        cur = stored.get(m.workgroup_id)
        stored[m.workgroup_id] = m if cur is None else _better_membership(m, cur)

    candidates: dict[int, Workgroup] = {
        m.workgroup_id: m.workgroup for m in stored.values()
    }

    # Term registrations grant offering membership (seminar / reading group).
    # A registration on a committee-organized event (a Day of Assembly, say)
    # does NOT make you a member of that committee, so gate on OFFERING_KINDS —
    # mirroring Workgroup.is_member.
    reg_wg_ids: set[int] = set()
    regs = (
        Registration.objects
        .filter(
            user=user,
            status__in=(Registration.Status.PAID, Registration.Status.COMPED),
        )
        .select_related("event", "event__workgroup")
    )
    for r in regs:
        wg = r.event.workgroup
        if wg is not None and wg.kind in Workgroup.OFFERING_KINDS:
            candidates.setdefault(wg.id, wg)
            reg_wg_ids.add(wg.id)

    # Role-derived membership (auto_member_role == my role).
    role = getattr(getattr(user, "profile", None), "role", None)
    if role:
        for wg in Workgroup.objects.filter(auto_member_role=role):
            candidates.setdefault(wg.id, wg)

    rows: list[MyGroup] = []
    for wg_id, wg in candidates.items():
        m = stored.get(wg_id)
        is_current = wg.is_member(user)
        # A stored row (any status) always counts as "have been in"; a derived
        # or role membership belongs only while current or archive-accessible.
        if m is None and not is_current and not wg.has_archive_access(user):
            continue
        if m is not None:
            role_label = m.role_label
            is_lead = m.role in WorkgroupMembership.LEAD_ROLES
            ended_on = m.end_date
            via_registration = False
        elif wg_id in reg_wg_ids:
            role_label = "Participant"
            is_lead = False
            ended_on = None
            via_registration = True
        else:  # role-derived
            role_label = "Member"
            is_lead = False
            ended_on = None
            via_registration = False
        rows.append(
            MyGroup(
                workgroup=wg,
                role_label=role_label,
                is_lead=is_lead,
                is_current=is_current,
                ended_on=ended_on,
                archived=wg.is_archived,
                via_registration=via_registration,
            )
        )
    return rows


def my_events(user, exclude_workgroup_ids=()) -> list[MyEvent]:
    """Standalone events the user is registered for (paid / comped) that aren't
    already represented by a group on the page.

    Seminars and reading groups surface as *groups* (their workgroup is in
    ``exclude_workgroup_ids``), so they're skipped here; what's left is the
    Programming-Committee-organized and one-off events — Days of Assembly,
    Working Days, special events, scholarly seminars — plus any event with no
    group at all. Confirmed (paid/comped) registrations show throughout;
    awaiting-payment ones show only while the event is still upcoming (an
    expired unpaid registration is abandoned, not a thing to nag about), with a
    ``needs_payment`` nudge. Upcoming first, then most-recent past.
    """
    if not getattr(user, "is_authenticated", False):
        return []
    exclude = set(exclude_workgroup_ids)
    today = datetime.date.today()
    seen: set[int] = set()
    events: list[MyEvent] = []
    regs = (
        Registration.objects
        .filter(
            user=user,
            status__in=(
                Registration.Status.PAID,
                Registration.Status.COMPED,
                Registration.Status.AWAITING_PAYMENT,
            ),
        )
        .select_related("event", "event__workgroup")
    )
    for r in regs:
        ev = r.event
        if ev is None or ev.id in seen:
            continue
        # Covered by a group shown above (a seminar / reading group / cartel
        # you belong to) — don't list the event again.
        if ev.workgroup_id and ev.workgroup_id in exclude:
            continue
        is_upcoming = not (ev.end_date and ev.end_date < today)
        # Don't nag about an unpaid registration for an event that's already
        # over — it was abandoned.
        if r.status == Registration.Status.AWAITING_PAYMENT and not is_upcoming:
            continue
        seen.add(ev.id)
        events.append(
            MyEvent(
                event=ev, registration=r, status=r.status, is_upcoming=is_upcoming
            )
        )

    # Upcoming block first (soonest first), then the past (most recent first).
    def _order(e):
        ordinal = e.event.start_date.toordinal()
        return (0, ordinal) if e.is_upcoming else (1, -ordinal)

    events.sort(key=_order)
    return events


#: Display order + plural labels for grouping a member's groups by kind. Kept
#: here (not in ``workgroups.views``) so non-view callers — the My LSP hub — can
#: bucket groups without importing a views module.
GROUP_KIND_LABELS = [
    (Workgroup.Kind.SEMINAR, "Seminars"),
    (Workgroup.Kind.CARTEL, "Cartels"),
    (Workgroup.Kind.COMMITTEE, "Committees"),
    (Workgroup.Kind.WORKING_GROUP, "Working Groups"),
    (Workgroup.Kind.READING_GROUP, "Reading Groups"),
]


def my_groups_by_kind(rows):
    """Bucket :class:`MyGroup` rows by kind in :data:`GROUP_KIND_LABELS` order;
    within a kind, by academic year (latest first) then name. Returns a list of
    ``(plural_label, [rows])``."""
    buckets: dict = {}
    for r in rows:
        buckets.setdefault(r.kind, []).append(r)
    out = []
    for kind, label in GROUP_KIND_LABELS:
        items = buckets.get(kind)
        if not items:
            continue
        items.sort(key=lambda r: r.name.lower())
        items.sort(key=lambda r: r.academic_year or "", reverse=True)
        out.append((label, items))
    return out


def ensure_calendar_token(user) -> str:
    """The user's personal calendar-feed token, minted on first use. Writes to
    the DB — callers must not invoke it while impersonating."""
    import secrets

    profile = user.profile
    if not profile.calendar_token:
        profile.calendar_token = secrets.token_urlsafe(24)
        profile.save(update_fields=["calendar_token"])
    return profile.calendar_token
