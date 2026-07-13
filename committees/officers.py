"""School officers (President / Vice-President) derived from the Board roster.

The Board committee's serving Chair / Co-chair ARE the school's President /
Vice-President. This module keeps the two ``core.StaffRole`` rows in lockstep
with that roster (one-directional: roster -> StaffRole), so the Board's Settings
roster is the single place officers are set. See
docs/superpowers/specs/2026-07-12-shared-school-officers-design.md.
"""

from __future__ import annotations


def sync_school_officers() -> None:
    """President holders := Board serving Chairs; Vice-President holders :=
    Board serving Co-chairs. Idempotent — recomputed and ``.set()`` each call."""
    from committees.models import Committee
    from core.models import StaffRole
    from workgroups.models import WorkgroupMembership

    board = (
        Committee.objects.filter(slug="board").select_related("workgroup").first()
    )
    if board is None or board.workgroup_id is None:
        return
    serving = list(board.workgroup.memberships.serving().select_related("user"))
    mapping = {
        WorkgroupMembership.Role.CHAIR: StaffRole.PRESIDENT,
        WorkgroupMembership.Role.CO_CHAIR: StaffRole.VICE_PRESIDENT,
    }
    for role_value, key in mapping.items():
        holders = [m.user for m in serving if m.role == role_value]
        role = StaffRole.objects.filter(key=key).first()
        if role is not None:
            role.holders.set(holders)
