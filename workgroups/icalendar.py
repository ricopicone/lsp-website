"""Minimal iCalendar (RFC 5545) feed builder for workgroup meetings — no
dependency. One VEVENT per materialized occurrence; cancelled occurrences are
emitted with ``STATUS:CANCELLED`` so subscribers see them drop off.

The personal feed also folds in registered *events* (seminar sessions, Days of
Assembly, …) passed as normalized ``entries`` dicts (see ``_entry_lines``)."""

from __future__ import annotations

from datetime import timedelta
from datetime import timezone as _dt_timezone


def _utc(dt) -> str:
    return dt.astimezone(_dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _date(d) -> str:
    return d.strftime("%Y%m%d")


def _esc(text: str) -> str:
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _entry_lines(e: dict, host: str) -> list[str]:
    """VEVENT lines for a normalized event entry (a registered event or one of
    its sessions). Keys: ``uid``, ``dtstamp``, ``summary``; optional ``start``/
    ``end`` (datetimes, or dates when ``all_day``), ``all_day``, ``location``,
    ``description``, ``url``."""
    out = [
        "BEGIN:VEVENT",
        f"UID:{e['uid']}@{host}",
        f"DTSTAMP:{_utc(e['dtstamp'])}",
    ]
    if e.get("all_day"):
        out.append(f"DTSTART;VALUE=DATE:{_date(e['start'])}")
        if e.get("end"):
            # DTEND is exclusive for all-day events — add a day so the span
            # covers the final date.
            out.append(f"DTEND;VALUE=DATE:{_date(e['end'] + timedelta(days=1))}")
    else:
        out.append(f"DTSTART:{_utc(e['start'])}")
        if e.get("end"):
            out.append(f"DTEND:{_utc(e['end'])}")
    out.append(f"SUMMARY:{_esc(e['summary'])}")
    if e.get("location"):
        out.append(f"LOCATION:{_esc(e['location'])}")
    if e.get("description"):
        out.append(f"DESCRIPTION:{_esc(e['description'])}")
    if e.get("url"):
        out.append(f"URL:{e['url']}")
    out += ["STATUS:CONFIRMED", "END:VEVENT"]
    return out


def build_ics(calendar_name: str, meetings, *, host: str, entries=()) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Lacanian School//Workgroups//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_esc(calendar_name)}",
    ]
    for m in meetings:
        # The link a subscriber taps to join: an explicit external URL (Zoom,
        # …) wins; otherwise the group's in-site video room (set on the meeting
        # by the feed view as ``join_url`` when video is enabled). Login is the
        # gate, so the link itself is not a credential — safe to sit in a synced
        # calendar.
        join = m.online_url or getattr(m, "join_url", "")
        desc = []
        if m.note:
            desc.append(m.note)
        if join:
            desc.append(f"Join: {join}")
        if m.location and join:
            # Keep a physical room in the body when LOCATION is carrying the
            # join link instead.
            desc.append(f"Location: {m.location}")
        if m.access_info:
            desc.append(m.access_info)
        if m.minutes:
            desc.append("Minutes recorded.")
        lines += [
            "BEGIN:VEVENT",
            f"UID:wg-meeting-{m.pk}@{host}",
            f"DTSTAMP:{_utc(m.created_at)}",
            f"DTSTART:{_utc(m.starts_at)}",
        ]
        if m.ends_at:
            lines.append(f"DTEND:{_utc(m.ends_at)}")
        lines.append(f"SUMMARY:{_esc(m.title or m.workgroup.name)}")
        # Put the join link in LOCATION so calendar apps surface a one-tap
        # "Join"; a physical room wins only when there's no join link.
        loc = m.location if (m.location and not join) else join
        if loc:
            lines.append(f"LOCATION:{_esc(loc)}")
        if desc:
            lines.append(f"DESCRIPTION:{_esc(chr(10).join(desc))}")
        if join:
            lines.append(f"URL:{join}")
        lines.append("STATUS:" + ("CANCELLED" if m.cancelled else "CONFIRMED"))
        lines.append("END:VEVENT")
    for e in entries:
        lines += _entry_lines(e, host)
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
