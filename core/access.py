"""Staff-role access checks — the single mechanism for coordinator/staff roles.

Roles and their holders live in ``core.StaffRole`` (LSP Staff, Cartel
Coordinator, Web Coordinator, …). ``has_staff_role`` is *exact*: it reflects
explicit holdership only, with no superuser magic, so it can back
security-sensitive checks (Parlêtre channel access, board entry, cartel
review) without quietly widening them. The convenience "a superuser can reach
any control panel" lives in the panel decorators below, not here.
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


def has_any_staff_role(user) -> bool:
    """True iff ``user`` holds at least one staff role."""
    if not getattr(user, "is_authenticated", False):
        return False
    return user.staff_roles.exists()


def can_access_staff_tools(user) -> bool:
    """The entry gate to the /staff/ hub: any staff role, Django staff (who get
    the treasurer + admin tools), or a superuser."""
    if not getattr(user, "is_authenticated", False):
        return False
    return user.is_superuser or user.is_staff or has_any_staff_role(user)


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


def staff_tools_required(view):
    """Decorator: the /staff/ hub gate (see ``can_access_staff_tools``)."""
    return _guard(view, can_access_staff_tools)
