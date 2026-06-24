"""Who may run the Applications Coordinator console.

The coordinator is an officer of the Meeting of Analysts (a workgroup role)
who facilitates admissions — triage, staffing interviewers, chasing reports —
while the Meeting itself keeps the decision. Gated to that role (+ superusers),
deliberately *not* generic ``is_staff``.
"""

from __future__ import annotations

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from workgroups.permissions import is_applications_coordinator


def can_coordinate_applications(user) -> bool:
    return is_applications_coordinator(user)


def is_analyst(user) -> bool:
    """An active Analyst of the School — eligible to interview applicants and
    use the Analyst page. Superusers included for support."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    from accounts.models import Profile

    profile = getattr(user, "profile", None)
    return bool(
        profile
        and profile.role == Profile.Role.ANALYST
        and profile.standing == Profile.Standing.ACTIVE
    )


def analyst_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not is_analyst(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def coordinator_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not can_coordinate_applications(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper
