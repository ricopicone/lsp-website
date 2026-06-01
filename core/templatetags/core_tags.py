"""Template helpers for the core app."""

from __future__ import annotations

from django import template

from core.staff import can_access_staff_tools

register = template.Library()


@register.filter(name="has_staff_tools")
def has_staff_tools(user) -> bool:
    """True if the user can reach the /staff/ hub (any staff role, Django staff, or superuser)."""
    return can_access_staff_tools(user)
