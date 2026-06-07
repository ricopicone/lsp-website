"""Export suggestions as structured markdown briefs for a Claude Code session.

The point of the suggestion box is that staff can hand a batch of member
suggestions to a coding session with as little re-discovery as possible. Each
brief names *what* to change, *where* (the captured page path **plus the Django
view + URL pattern that owns it**, resolved here so the session doesn't have to
grep for it), and the member's own description. ``write_briefs`` also refreshes an
``INDEX.md`` checklist a session can work through top to bottom, and stamps
``exported_at`` so a later ``--unexported`` run skips what's already been handed off.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from django.urls import Resolver404, resolve
from django.utils import timezone


def resolve_route(page_url: str) -> dict | None:
    """Map a captured site path to the view + URL name that serve it.

    Returns ``{"view": dotted.path, "url_name": "ns:name", "kwargs": {...}}`` or
    ``None`` when the path is blank or doesn't resolve (e.g. a stale or external
    URL). Never raises.
    """
    if not page_url:
        return None
    path = urlparse(page_url).path or page_url
    try:
        match = resolve(path)
    except Resolver404:
        return None
    view = match.func
    view_path = f"{view.__module__}.{getattr(view, '__qualname__', view.__name__)}"
    url_name = (
        f"{match.namespace}:{match.url_name}" if match.namespace else (match.url_name or "")
    )
    return {"view": view_path, "url_name": url_name, "kwargs": dict(match.kwargs)}


def build_brief(suggestion) -> str:
    """Render one suggestion as a self-contained markdown brief."""
    s = suggestion
    who = (
        (s.submitted_by.get_full_name() or s.submitted_by.email)
        if s.submitted_by else "(unknown)"
    )
    lines: list[str] = []

    # YAML-ish frontmatter for quick machine/eyeball scanning.
    lines += [
        "---",
        f"id: {s.pk}",
        f"kind: {s.kind}",
        f"status: {s.status}",
        f"priority: {s.priority or 'unset'}",
        f"submitted_by: {who}",
        f"page_url: {s.page_url or '(none)'}",
        f"created_at: {s.created_at.isoformat()}",
        "---",
        "",
        f"# Suggestion #{s.pk}: {s.title}",
        "",
        f"**Kind:** {s.get_kind_display()} · **Status:** {s.get_status_display()}"
        + (f" · **Priority:** {s.get_priority_display()}" if s.priority else ""),
        "",
    ]

    # Where — the page and the code that owns it.
    lines.append("## Where")
    if s.page_url:
        lines.append(f"- **Page:** `{s.page_url}`"
                     + (f" — {s.page_title}" if s.page_title else ""))
        route = resolve_route(s.page_url)
        if route:
            lines.append(f"- **View:** `{route['view']}`")
            if route["url_name"]:
                lines.append(f"- **URL name:** `{route['url_name']}`")
            if route["kwargs"]:
                lines.append(f"- **URL kwargs:** `{json.dumps(route['kwargs'])}`")
        else:
            lines.append("- **View:** _path did not resolve (stale or external)._")
    else:
        lines.append("- Not anchored to a specific page (general suggestion).")
    lines.append("")

    # What.
    lines.append("## Details")
    lines.append(s.body.strip() if s.body.strip() else "_(no description given)_")
    lines.append("")

    if s.context:
        lines.append("## Browser context")
        lines.append("```json")
        lines.append(json.dumps(s.context, indent=2, ensure_ascii=False))
        lines.append("```")
        lines.append("")

    if s.screenshot:
        lines.append("## Screenshot")
        lines.append(f"- `{s.screenshot.name}` (export with `--with-screenshots` "
                     "to download a local copy)")
        lines.append("")

    if s.staff_notes.strip():
        lines.append("## Staff notes")
        lines.append(s.staff_notes.strip())
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _index(suggestions) -> str:
    lines = ["# Suggestions — export index", ""]
    lines.append(f"{len(suggestions)} suggestion(s). Work through them top to bottom.")
    lines.append("")
    for s in suggestions:
        anchor = f" — `{s.page_url}`" if s.page_url else ""
        lines.append(
            f"- [ ] [#{s.pk}](./suggestion-{s.pk}.md) — {s.title} "
            f"({s.get_kind_display()}, {s.get_status_display()}){anchor}"
        )
    lines.append("")
    return "\n".join(lines)


def write_briefs(queryset, out_dir, *, with_screenshots: bool = False) -> list[Path]:
    """Write a markdown brief per suggestion + an INDEX.md, and stamp each row's
    ``exported_at``. Returns the list of written brief paths.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    suggestions = list(queryset)

    written: list[Path] = []
    for s in suggestions:
        brief_path = out / f"suggestion-{s.pk}.md"
        brief_path.write_text(build_brief(s), encoding="utf-8")
        written.append(brief_path)
        if with_screenshots and s.screenshot:
            shots = out / "screenshots"
            shots.mkdir(exist_ok=True)
            name = s.screenshot.name.rsplit("/", 1)[-1]
            dest = shots / f"suggestion-{s.pk}-{name}"
            with s.screenshot.open("rb") as src:
                dest.write_bytes(src.read())

    (out / "INDEX.md").write_text(_index(suggestions), encoding="utf-8")

    if suggestions:
        from .models import Suggestion

        Suggestion.objects.filter(pk__in=[s.pk for s in suggestions]).update(
            exported_at=timezone.now()
        )
    return written
