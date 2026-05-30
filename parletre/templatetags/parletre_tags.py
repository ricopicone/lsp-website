"""Template helpers for Parlêtre (nav gating)."""

from django import template

from parletre.permissions import is_member

register = template.Library()


@register.filter(name="is_parletre_member")
def is_parletre_member(user) -> bool:
    """True if ``user`` may enter Parlêtre (drives the nav link)."""
    return is_member(user)
