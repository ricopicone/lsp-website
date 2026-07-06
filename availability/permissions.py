"""Who may run the analyst-availability console.

Gated to the Applications Coordinator — an officer role on the Meeting of
Analysts workgroup (plus superusers). The same role facilitates admissions,
so availability and admissions are one coordinator's workspace. Deliberately
*not* generic ``is_staff``: the data is members-internal.
"""

from __future__ import annotations

from workgroups.permissions import is_applications_coordinator


def can_manage_availability(user) -> bool:
    return is_applications_coordinator(user)
