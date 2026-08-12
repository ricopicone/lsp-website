"""Permission helpers for event-level views (PROG-7, PROG-8)."""

from __future__ import annotations

from workgroups.models import WorkgroupMembership
from workgroups.permissions import is_workgroup_lead

#: Event types whose workgroup leadership confers the event's faculty surfaces.
#: A seminar or reading group owns its workgroup, so whoever leads that group
#: runs the offering: faculty for a seminar, and the ORGANIZER conveners a
#: reading group gets instead (``EventProposal.approve`` — "reading groups are
#: organizer-led, not faculty"). Cartels are member-led and stay out; the
#: PC-organized types share the Programming Committee's own workgroup, where
#: "lead" would mean "leads the PC" — already covered, more precisely, by the
#: committee clause in ``can_edit_event``.
LEAD_LED_EVENT_TYPES = frozenset({"seminar", "reading_group"})


def _leads_offering(user, event) -> bool:
    """Whether ``user`` leads the workgroup of an offering they'd thereby run."""
    if event.event_type not in LEAD_LED_EVENT_TYPES or not event.workgroup_id:
        return False
    return is_workgroup_lead(user, event.workgroup)


def offering_leads(event) -> list:
    """Everyone who runs this offering: its faculty, plus the lead-role members
    of its own workgroup for the types where leading the group *is* running the
    offering (a reading group's conveners hold ORGANIZER, not FACULTY — #495).

    This is the audience for anything that asks the people running an event to
    act. ``can_edit_event`` has always let a convener approve a registration;
    the approval notice went to ``Event.faculty_members()`` alone, so on a
    convener-led offering it reached nobody and fell back to the school's own
    support address (task #564).

    ``faculty_members()`` answers a different question — who *teaches* this —
    and drives bylines, the roster, and the PC form's initial selection, so it
    stays as it is.
    """
    people = list(event.faculty_members())
    if event.event_type in LEAD_LED_EVENT_TYPES and event.workgroup_id:
        seen = {u.pk for u in people}
        for m in event.workgroup.memberships.serving().filter(
            role__in=WorkgroupMembership.LEAD_ROLES,
        ).select_related("user"):
            if m.user.pk not in seen:
                seen.add(m.user.pk)
                people.append(m.user)
    return people


def _is_lsp_staff(user) -> bool:
    from core.access import has_staff_role
    from core.models import StaffRole

    return has_staff_role(user, StaffRole.LSP_STAFF)


def can_edit_event(user, event) -> bool:
    """True if ``user`` may edit ``event`` (PROG-7) or see its faculty surfaces (PROG-8).

    Event-edit rights come from: Django staff, the LSP Staff designation (which
    replaced the former 'lsp-staff' committee), the event's own faculty, the
    presenters of a PC-organized event (``Event.is_presenter``, task #463), the
    leads of a seminar's or reading group's own workgroup (task #495 — a reading
    group's conveners hold ORGANIZER, not FACULTY), or Programming Committee
    membership.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff or _is_lsp_staff(user):
        return True
    if event.is_faculty(user) or event.is_presenter(user):
        return True
    if _leads_offering(user, event):
        return True
    return WorkgroupMembership.objects.serving().filter(
        user=user,
        workgroup__committee__slug="programming-committee",
    ).exists()


def is_program_committee(user) -> bool:
    """True if ``user`` is a current member of the Programming Committee.

    Used to gate Program preview before publication and the
    Program Committee admin interface.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    return WorkgroupMembership.objects.serving().filter(
        user=user,
        workgroup__committee__slug="programming-committee",
    ).exists()


def is_change_reviewer(user) -> bool:
    """True if ``user`` reviews faculty content changes (#295) — i.e. is on the
    Programming Committee or holds a staff designation. Reviewers get the extra
    "administrative change" option in the certify-or-submit dialog and may
    decide the committee queue.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    return user.is_staff or _is_lsp_staff(user) or is_program_committee(user)
