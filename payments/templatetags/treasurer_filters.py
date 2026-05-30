"""Template filters used by the treasurer admin templates."""

from django import template
from django.utils.html import format_html

register = template.Library()


@register.filter
def tier_for(dues_period, role: str):
    """Return the dues amount owed by ``role`` under ``dues_period``."""
    if dues_period is None or not role:
        return ""
    return dues_period.amount_for_role(role) or ""


@register.filter
def usd(value):
    """Format a numeric value as a USD currency string (e.g. ``$100.00``).

    Returns ``""`` for None so it can be used unconditionally on
    aggregate query results that may be None.
    """
    if value is None or value == "":
        return ""
    try:
        return f"${float(value):.2f}"
    except (ValueError, TypeError):
        return f"${value}"


# Map status string -> (DaisyUI badge color, display label).
# Covers both Payment and TuitionEnrollment statuses since their strings
# don't collide. Add new statuses here, not in templates.
_STATUS_BADGE = {
    # Payment.Status
    "pending":      ("warning", "Pending"),
    "succeeded":    ("success", "Succeeded"),
    "failed":       ("error",   "Failed"),
    "refunded":     ("info",    "Refunded"),
    # TuitionEnrollment.Status
    "paid_in_full": ("success", "Paid in full"),
    "payment_plan": ("info",    "Payment plan"),
    "committed":    ("warning", "Committed"),
    "skipping":     ("ghost",   "Skipping"),
}


@register.simple_tag
def status_badge(status: str):
    """Render a DaisyUI badge for a Payment or TuitionEnrollment status.

    Centralizes the status → (color, label) mapping so templates don't
    repeat ``{% if status == "x" %}...{% elif... %}`` chains.

    Unknown statuses fall back to a neutral ghost badge with the raw
    string title-cased.
    """
    color, label = _STATUS_BADGE.get(
        status, ("ghost", (status or "").replace("_", " ").title()),
    )
    return format_html(
        '<span class="badge badge-{} badge-sm">{}</span>',
        color, label,
    )
