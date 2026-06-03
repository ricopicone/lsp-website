"""Minimal iCalendar (RFC 5545) feed builder for workgroup meetings — no
dependency. One VEVENT per materialized occurrence; cancelled occurrences are
emitted with ``STATUS:CANCELLED`` so subscribers see them drop off."""

from __future__ import annotations

from datetime import timezone as _dt_timezone


def _utc(dt) -> str:
    return dt.astimezone(_dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _esc(text: str) -> str:
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def build_ics(calendar_name: str, meetings, *, host: str) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Lacanian School//Workgroups//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_esc(calendar_name)}",
    ]
    for m in meetings:
        desc = []
        if m.note:
            desc.append(m.note)
        if m.online_url:
            desc.append(f"Join: {m.online_url}")
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
        if m.location:
            lines.append(f"LOCATION:{_esc(m.location)}")
        if desc:
            lines.append(f"DESCRIPTION:{_esc(chr(10).join(desc))}")
        if m.online_url:
            lines.append(f"URL:{m.online_url}")
        lines.append("STATUS:" + ("CANCELLED" if m.cancelled else "CONFIRMED"))
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
