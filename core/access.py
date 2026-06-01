"""Staff-role access primitives — the single mechanism for staff/coordinator roles.

Roles and their holders live in ``core.StaffRole`` (LSP Staff, Cartel
Coordinator, Web Coordinator, Treasurer, …). ``has_staff_role`` is *exact*: it
reflects explicit holdership only, with no superuser magic, so it can back
security-sensitive checks (Parlêtre channel access, board entry, cartel review)
without quietly widening them. The convenience "a superuser can reach any
control panel" lives in the panel decorators, not here.

The /staff/ hub's own entry gate (which also considers Django staff and
committee membership) lives in ``core.staff`` next to the panel registry.
"""

from __future__ import annotations

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def has_staff_role(user, *keys: str) -> bool:
    """True iff ``user`` is an explicit holder of one of ``keys``."""
    if not getattr(user, "is_authenticated", False):
        return False
    return user.staff_roles.filter(key__in=keys).exists()


def _guard(view, predicate):
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not predicate(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return _wrapped


def staff_role_required(*keys: str):
    """Decorator: require one of ``keys`` (superusers always pass — panel only)."""

    def decorator(view):
        return _guard(view, lambda u: u.is_superuser or has_staff_role(u, *keys))

    return decorator
