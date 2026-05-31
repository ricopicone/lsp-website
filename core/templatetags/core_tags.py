"""Template helpers for the core app."""

from __future__ import annotations

from django import template

from core.access import has_any_staff_role

register = template.Library()


@register.filter(name="is_coordinator")
def is_coordinator(user) -> bool:
    """True if the user can reach the Web Coordinator hub (any staff role)."""
    return has_any_staff_role(user)
