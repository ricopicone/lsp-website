"""Datetime-rendering filters that respect the active timezone + show PT on hover.

LSP members are distributed across timezones; people in PT historically
assume "the time" means PT, while members elsewhere now see their own
zone. The hover tooltip carries the PT equivalent so PT-native readers
can cross-reference quickly.

Output shape (``user_time`` example for a NY user looking at a 5pm PT
session):

    <time datetime="2026-09-15T17:00:00-07:00"
          title="5:00 PM PT (Sept 15)">
      8:00 PM EDT
    </time>
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
    """Human TZ abbreviation for ``value`` in ``zone`` (handles DST)."""
    in_zone = value.astimezone(zone)
    abbr = in_zone.strftime("%Z")
    # Normalize PDT/PST → PT for the LSP convention (members usually say "PT")
    # but keep the precise abbreviation in cross-zone titles to disambiguate.
    if abbr in ("PDT", "PST"):
        return "PT"
    return abbr


def _hover_title(value: _dt.datetime) -> str:
    """The text for the title="..." tooltip — always Pacific Time."""
    pt = value.astimezone(PT)
    # Strip leading 0 from %I (12-hour) for nicer display.
    time_str = pt.strftime("%I:%M %p").lstrip("0")
    date_str = pt.strftime("%b %-d")  # Sept 15 — %-d is non-portable but works on Linux/macOS
    # On platforms without %-d (Windows), fall back to a manual strip.
    if "%-d" in date_str or date_str.startswith("0"):
        date_str = pt.strftime("%b ") + str(pt.day)
    return f"{time_str} PT ({date_str})"


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
def user_datetime(value):
    """Render a datetime as a hovered ``<time>`` showing FULL DATE + TIME
    in the active timezone, with the PT equivalent in the title.

    Use this in standalone contexts (event detail headers, email bodies)
    where the date isn't obvious from neighboring elements.
    """
    if value is None:
        return ""
    active = timezone.get_current_timezone()
    local = value.astimezone(active)
    # "Tue, Sep 15, 8:00 PM EDT"
    date_str = local.strftime("%a, %b ") + str(local.day)
    time_str = local.strftime("%I:%M %p").lstrip("0")
    abbr = _tz_abbr(value, active)
    display = f"{date_str}, {time_str} {abbr}"
    iso = local.isoformat()
    title = _hover_title(value)
    return format_html(
        '<time datetime="{}" title="{}">{}</time>',
        iso, title, display,
    )


@register.simple_tag(takes_context=True)
def user_tz_name(context):
    """Return the active timezone's IANA name as a string.

    Used to seed FullCalendar's ``timeZone`` option for logged-in users.
    """
    return str(timezone.get_current_timezone())
