"""Datetime-rendering filters that respect the active timezone + show PT on hover.

LSP members are distributed across timezones; people in PT historically
assume "the time" means PT, while members elsewhere now see their own
zone. The hover tooltip carries the PT equivalent so PT-native readers
can cross-reference quickly.

Output shape (``user_time`` example for a NY user looking at a 5pm PDT
session in October):

    <time datetime="2026-10-15T17:00:00-07:00"
          title="5:00 PM PDT (Oct 15)">
      8:00 PM EDT
    </time>

We use the explicit ``PDT``/``PST`` (and ``EDT``/``EST``, ``CET``/``CEST``,
etc.) rather than the generic ``PT``/``ET``. LSP members regularly
confuse the daylight and standard variants, which causes real
"I showed up an hour off" mistakes around DST transitions — the
explicit form removes that whole class of error.
"""

from __future__ import annotations

import datetime as _dt
from zoneinfo import ZoneInfo

from django import template
from django.utils import timezone
from django.utils.html import format_html

register = template.Library()

PT = ZoneInfo("America/Los_Angeles")


def _format_in_zone(value: _dt.datetime, zone: ZoneInfo, fmt: str) -> str:
    """Render ``value`` in ``zone`` using a strftime format string."""
    in_zone = value.astimezone(zone)
    # %-I is non-portable; we strip leading zero manually to stay safe.
    formatted = in_zone.strftime(fmt)
    return formatted.replace(" 0", " ").lstrip("0") if fmt.startswith("%I") else formatted


def _tz_abbr(value: _dt.datetime, zone: ZoneInfo) -> str:
    """Explicit TZ abbreviation for ``value`` in ``zone`` (handles DST).

    Returns ``PDT``/``PST`` etc., not the generic ``PT`` — see the
    module docstring for why.
    """
    return value.astimezone(zone).strftime("%Z")


def _hover_title(value: _dt.datetime) -> str:
    """The text for the title="..." tooltip — always Pacific Time, with
    the explicit PDT/PST so the cross-reference is unambiguous around
    DST."""
    pt = value.astimezone(PT)
    abbr = pt.strftime("%Z")  # PDT or PST
    time_str = pt.strftime("%I:%M %p").lstrip("0")
    date_str = pt.strftime("%b ") + str(pt.day)
    return f"{time_str} {abbr} ({date_str})"


@register.filter
def user_date(value, show_year=True):
    """Render a datetime as a compact DATE-ONLY ``<time>`` ("Jan 10, 2026" —
    no weekday, no time) with the full local date+time and the PT equivalent
    in the hover title. For dense tables like the treasurer's Payments tab.
    """
    if value is None:
        return ""
    active = timezone.get_current_timezone()
    local = value.astimezone(active)
    display = local.strftime("%b ") + str(local.day)
    if show_year:
        display += f", {local.year}"
    time_str = local.strftime("%I:%M %p").lstrip("0")
    abbr = _tz_abbr(value, active)
    full_local = (local.strftime("%a, %b ") + str(local.day)
                  + f", {local.year}, {time_str} {abbr}")
    title = f"{full_local} — {_hover_title(value)}"
    iso = local.isoformat()
    return format_html(
        '<time datetime="{}" title="{}">{}</time>', iso, title, display,
    )


@register.filter
def user_time(value):
    """Render a datetime as a hovered ``<time>`` showing TIME ONLY in the
    active timezone, with the PT equivalent in the title attribute.

    Use this when the date is already known from context (e.g. inside a
    table row whose left column is the date).
    """
    if value is None:
        return ""
    active = timezone.get_current_timezone()
    local = value.astimezone(active)
    time_str = local.strftime("%I:%M %p").lstrip("0")
    abbr = _tz_abbr(value, active)
    display = f"{time_str} {abbr}"
    iso = local.isoformat()
    title = _hover_title(value)
    return format_html(
        '<time datetime="{}" title="{}">{}</time>',
        iso, title, display,
    )


@register.filter
def user_datetime(value, show_year=False):
    """Render a datetime as a hovered ``<time>`` showing FULL DATE + TIME
    in the active timezone, with the PT equivalent in the title.

    Use this in standalone contexts (event detail headers, email bodies)
    where the date isn't obvious from neighboring elements. Pass a truthy
    argument (``|user_datetime:True``) to include the year — useful in
    tables that span multiple years, like the treasurer's ledger.
    """
    if value is None:
        return ""
    active = timezone.get_current_timezone()
    local = value.astimezone(active)
    # "Tue, Sep 15, 8:00 PM EDT" (or "Tue, Sep 15, 2026, …" with show_year)
    date_str = local.strftime("%a, %b ") + str(local.day)
    if show_year:
        date_str += f", {local.year}"
    time_str = local.strftime("%I:%M %p").lstrip("0")
    abbr = _tz_abbr(value, active)
    display = f"{date_str}, {time_str} {abbr}"
    iso = local.isoformat()
    title = _hover_title(value)
    return format_html(
        '<time datetime="{}" title="{}">{}</time>',
        iso, title, display,
    )


@register.filter
def user_datetime_text(value):
    """Plain-text sibling of ``user_datetime`` for email bodies: the full
    date + time in the active timezone with the Pacific equivalent in
    parentheses, and no markup."""
    if value is None:
        return ""
    active = timezone.get_current_timezone()
    local = value.astimezone(active)
    date_str = local.strftime("%a, %b ") + str(local.day) + f", {local.year}"
    time_str = local.strftime("%I:%M %p").lstrip("0")
    abbr = _tz_abbr(value, active)
    text = f"{date_str}, {time_str} {abbr}"
    pt = value.astimezone(PT)
    if pt.strftime("%Z") != abbr:
        text += f" ({_hover_title(value)})"
    return text


@register.simple_tag(takes_context=True)
def user_tz_name(context):
    """Return the active timezone's IANA name as a string.

    Used to seed FullCalendar's ``timeZone`` option for logged-in users.
    """
    return str(timezone.get_current_timezone())
