"""Template helpers for the core app."""

from __future__ import annotations

from django import template

from core.staff import can_access_admin_tools

register = template.Library()


@register.filter(name="has_admin_tools")
def has_admin_tools(user) -> bool:
    """True if the user can reach the /admin-tools/ hub (staff role, Board, PC,
    Django staff, or superuser)."""
    return can_access_admin_tools(user)
