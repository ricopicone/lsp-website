"""Template filters used by the treasurer admin templates."""

import re

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

    Negatives read ``-$40.00``, not ``$-40.00`` — running balances go
    negative whenever a member is in credit.

    Returns ``""`` for None so it can be used unconditionally on
    aggregate query results that may be None.
    """
    return _money(value, places=2)


@register.filter
def usd0(value):
    """Format as a whole-dollar USD string with thousands commas, no cents
    (e.g. ``$2,500``). For compact rate/headline displays."""
    return _money(value, places=0)


def _money(value, *, places: int) -> str:
    if value is None or value == "":
        return ""
    try:
        amount = float(value)
    except (ValueError, TypeError):
        return f"${value}"
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.{places}f}"


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
    "plan_requested": ("warning", "Payment plan requested"),
    "committed":    ("warning", "Committed"),
    "skipping":     ("ghost",   "Skipping"),
    # LedgerSubmission.Status ("pending" reuses the Payment mapping above)
    "approved":     ("success", "Approved"),
    "declined":     ("error",   "Declined"),
}


_IMPORT_TAG_LABELS = {
    "tz-import": "Treasurer ledger ref",
    "stripe-import": "Stripe charge",
}

# A leading machine tag like ``[tz-import:tuition-24-25#1]`` optionally followed
# by trailing free text (e.g. a ``(provisional — …)`` parenthetical).
_TAG_RE = re.compile(r"^\[([a-z-]+):([^\]]+)\]\s*(.*)$")
# A bracketed marker without a colon, e.g. ``[assume-skip dues-24-25]``.
_BRACKET_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")


@register.filter
def provenance_lines(notes):
    """Turn a payment/enrollment ``notes`` string into readable display lines.

    Import rows carry a leading machine tag plus ``|``-separated annotations,
    e.g. ``[tz-import:tuition-24-25#1] | installment: 1st | method unrecorded in
    ledger``. The tag becomes a readable reference line; annotations pass
    through verbatim. Returns a list of non-empty strings (``[]`` for blank
    input).
    """
    if not notes or not str(notes).strip():
        return []
    segments = [s.strip() for s in str(notes).split("|")]
    segments = [s for s in segments if s]
    if not segments:
        return []

    first = segments[0]
    lines = []
    tag = _TAG_RE.match(first)
    if tag:
        kind, ref, trailing = tag.group(1), tag.group(2), tag.group(3).strip()
        label = _IMPORT_TAG_LABELS.get(
            kind,
            kind.replace("-import", "").replace("-", " ").title() + " ref",
        )
        line = f"{label} · {ref}"
        if trailing:
            line = f"{line} {trailing}"
        lines.append(line)
    else:
        bracket = _BRACKET_RE.match(first)
        if bracket:
            lines.append(
                f"{bracket.group(1).strip()} {bracket.group(2).strip()}".strip()
            )
        else:
            lines.append(first)

    lines.extend(segments[1:])
    return lines


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
