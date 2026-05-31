"""Gating for the Web Coordinator control panel(s).

Access is driven by ``core.StaffRole`` membership. Superusers implicitly hold
every role. These helpers are deliberately tiny so views and templates share
one source of truth.
"""

from __future__ import annotations

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def has_staff_role(user, *keys: str) -> bool:
    """True if ``user`` holds any of ``keys`` (superusers hold everything)."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    return user.staff_roles.filter(key__in=keys).exists()


def has_any_staff_role(user) -> bool:
    """True if ``user`` holds at least one staff role (or is a superuser)."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    return user.staff_roles.exists()


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
    """Decorator: require the user to hold one of ``keys`` (or be a superuser)."""

    def decorator(view):
        return _guard(view, lambda u: has_staff_role(u, *keys))

    return decorator


def coordinator_required(view):
    """Decorator: require any staff role — the entry gate to the hub."""
    return _guard(view, has_any_staff_role)
