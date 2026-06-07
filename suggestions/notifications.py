"""Notification wrappers for the suggestion box.

A filed suggestion raises an in-app bell row for each site triager (Web
Coordinator / Web Developer) — an operational signal, no email. A status change
notifies the submitter through their own preferences (in-app + optional email).
Everything routes through the single ``notifications.dispatch.notify`` chokepoint.
"""

from __future__ import annotations

from notifications.categories import Category
from notifications.dispatch import notify


def _triagers():
    from accounts.models import User
    from core.models import StaffRole

    return list(
        User.objects.filter(
            staff_roles__key__in=[StaffRole.WEB_COORDINATOR, StaffRole.WEB_DEVELOPER]
        ).distinct()
    )


def filed(suggestion, url: str) -> None:
    """Tell the site triagers a new suggestion arrived (in-app only)."""
    who = suggestion.submitted_by.get_full_name() if suggestion.submitted_by else "A member"
    for user in _triagers():
        notify(
            user, Category.SUGGESTION_FILED,
            title=f"New suggestion: {suggestion.title}",
            body=f"{who} suggested a change ({suggestion.get_kind_display()}).",
            url=url, target=suggestion, email=False, dedupe=False,
        )


def status_changed(suggestion, url: str) -> None:
    """Tell the submitter their suggestion's status changed."""
    if suggestion.submitted_by is None:
        return
    notify(
        suggestion.submitted_by, Category.SUGGESTION_UPDATE,
        title=f"Update on your suggestion: {suggestion.title}",
        body=f"Status: {suggestion.get_status_display()}.",
        url=url, target=suggestion,
    )
