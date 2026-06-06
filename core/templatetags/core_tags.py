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


@register.filter(name="is_lsp_member")
def is_lsp_member(user) -> bool:
    """True for an LSP member (full member, not an outside auditor) — used to
    gate member-only nav like proposing an event."""
    from accounts.permissions import is_lsp_member as _is_lsp_member

    return _is_lsp_member(user)
