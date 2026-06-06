"""Staff guides shown on the /guides/ index, gated to the viewer's roles.

These aren't Markdown files in this app—they're the existing in-tool Help pages
that already live next to each staff surface (the treasurer's help, the Program
Committee's admin guide, the groups guide). The Guides index just surfaces a
"Your staff guides" section linking to them, filtered by the same permission
checks that gate the pages themselves, so a viewer only sees the guides for
roles they hold.

Each gate is imported lazily inside its function to avoid import cycles (the
views these come from import models, templates, etc.).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from django.urls import NoReverseMatch, reverse


def _treasurer_gate(user) -> bool:
    from payments.views import _is_staff
    return _is_staff(user)


def _program_committee_gate(user) -> bool:
    from events.views import _is_pc_or_staff
    return _is_pc_or_staff(user)


def _admin_tools_gate(user) -> bool:
    from core.staff import can_access_admin_tools
    return can_access_admin_tools(user)


@dataclass(frozen=True)
class StaffGuide:
    title: str
    summary: str
    url_name: str
    gate: Callable[[object], bool]
    url_args: tuple = ()


STAFF_GUIDES: list[StaffGuide] = [
    StaffGuide(
        title="Treasurer",
        summary="Dues and tuition, recording offline payments, reconciliation, and exports.",
        url_name="treasurer_help",
        gate=_treasurer_gate,
    ),
    StaffGuide(
        title="Program Committee",
        summary="Soliciting and reviewing proposals, building the program, and publishing.",
        url_name="program_admin_help",
        gate=_program_committee_gate,
    ),
    StaffGuide(
        title="Running groups",
        summary="Cartels, working groups, and committees—roster, workspace, and lifecycle.",
        url_name="staff_doc",
        url_args=("groups-guide",),
        gate=_admin_tools_gate,
    ),
]


def for_user(user) -> list[dict]:
    """The staff guides this viewer may see, resolved to {title, summary, url}."""
    if not getattr(user, "is_authenticated", False):
        return []
    out: list[dict] = []
    for guide in STAFF_GUIDES:
        if not guide.gate(user):
            continue
        try:
            url = reverse(guide.url_name, args=guide.url_args)
        except NoReverseMatch:
            continue
        out.append({"title": guide.title, "summary": guide.summary, "url": url})
    return out
