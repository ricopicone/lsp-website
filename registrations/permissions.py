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


#: Shown to a guest who cannot register for a members-only event. Names the
#: restriction and both routes onward: the School's application, and the
#: faculty's own escape hatch, a code addressed to them (task #566).
MEMBERS_ONLY_REASON = (
    "Registration for this event is limited to members of the Lacanian "
    "School. If you have been invited to attend, ask the event's faculty "
    "for a registration code addressed to you."
)


def eligibility_block_reason(user, event) -> str | None:
    """Why ``user`` may not register for ``event``, or None to allow.

    Mirrors ``registrations.views._tuition_block_reason``: a member-facing
    string blocks, None admits.

    An event set to *Members only* admits members — the one definition,
    ``accounts.permissions.is_lsp_member``, so the three non-member roles
    (Auditor, Student, Prospective Applicant) and the resigned and removed
    standings are all guests here — plus anyone holding a live pricing code
    addressed to them by name, which is the faculty's own discretion (§4.1);
    an unrestricted code does not count, because a code that can be forwarded
    is not a decision about a person. The people who run the event pass too,
    so an outside speaker with a linked login (task #463) is never told
    "members only" about their own evening.
    """
    from events.models import Event

    if event.registration_eligibility != Event.RegistrationEligibility.MEMBERS_ONLY:
        return None

    from accounts.permissions import is_lsp_member

    if is_lsp_member(user):
        return None
    if not getattr(user, "is_authenticated", False):
        return MEMBERS_ONLY_REASON

    from events.models import PricingCode

    for code in PricingCode.objects.filter(event=event, restricted_to_user=user):
        if code.is_redeemable(user=user):
            return None

    from events.permissions import can_edit_event

    if can_edit_event(user, event) or event.is_presenter(user):
        return None
    return MEMBERS_ONLY_REASON
