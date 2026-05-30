"""Template filters used by the treasurer admin templates."""

from django import template

register = template.Library()


@register.filter
def tier_for(dues_period, role: str):
    """Return the dues amount owed by ``role`` under ``dues_period``."""
    if dues_period is None or not role:
        return ""
    return dues_period.amount_for_role(role) or ""
