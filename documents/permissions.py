"""Who may manage institutional documents.

The management surface lives under the Web Coordinator admin, so it is gated
to that role alone: pairing in the Web Developer would grant a child page to
a role that 403s on its parent hub, and the Web Developer already reaches
these fields through the Django admin.
"""

from __future__ import annotations

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from core.access import has_staff_role
from core.models import StaffRole


def can_manage_documents(user) -> bool:
    """True for the Web Coordinator (and superusers, who hold every role)."""
    if not getattr(user, "is_authenticated", False):
        return False
    return user.is_superuser or has_staff_role(user, StaffRole.WEB_COORDINATOR)


def manage_documents_required(view):
    """Anonymous → login (returning here); signed-in non-holder → 403.

    Shaped like ``core.access._guard`` but expressed over this app's own
    predicate, so the template flag and the view gate cannot drift.
    """

    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not can_manage_documents(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return _wrapped
