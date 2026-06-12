"""JSON shapes for the dev API.

The suggestion serializers mirror the markdown briefs in :mod:`suggestions.export`
— same fields, same ``page_url`` → view/url-name resolution — but as JSON a Claude
Code session can act on directly instead of reading from exported files.
"""

from __future__ import annotations

from suggestions.export import resolve_route


def _who(user) -> dict | None:
    if user is None:
        return None
    return {
        "id": user.pk,
        "name": user.get_full_name() or "",
        "email": user.email,
    }


def suggestion_summary(s) -> dict:
    """Compact shape for list endpoints."""
    return {
        "id": s.pk,
        "title": s.title,
        "kind": s.kind,
        "status": s.status,
        "priority": s.priority or None,
        "page_url": s.page_url or None,
        "submitted_by": _who(s.submitted_by),
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
        "exported_at": s.exported_at.isoformat() if s.exported_at else None,
    }


def suggestion_detail(s) -> dict:
    """Full shape for the detail endpoint — everything a brief carries, including
    the resolved view + URL name that owns the captured page."""
    data = suggestion_summary(s)
    data.update(
        {
            "kind_display": s.get_kind_display(),
            "status_display": s.get_status_display(),
            "priority_display": s.get_priority_display() if s.priority else None,
            "body": s.body,
            "page_title": s.page_title or None,
            "route": resolve_route(s.page_url),
            "context": s.context or {},
            "has_screenshot": bool(s.screenshot),
            "staff_notes": s.staff_notes,
            "reviewed_by": _who(s.reviewed_by),
            "reviewed_at": s.reviewed_at.isoformat() if s.reviewed_at else None,
        }
    )
    return data
