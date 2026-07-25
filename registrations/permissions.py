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
