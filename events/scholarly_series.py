"""The Scholarly Seminar Series page's helpers (task #851).

Every talk in the series is an event of type ``scholarly_seminar``, the ones
given before the site included (``manage.py import_scholarly_series_history``
made those), so the page lists events and nothing else.
"""

from __future__ import annotations


def coordinators() -> list:
    """Who holds the Scholarly Seminar Series Coordinator role, for the page:
    the description is introduced in their name, their bio sits beside it, and
    proposals go to them by way of their directory profile."""
    from accounts.models import User
    from core.models import StaffRole

    return list(
        User.objects.filter(
            is_active=True,
            staff_roles__key=StaffRole.SCHOLARLY_SEMINAR_COORDINATOR,
        ).select_related("profile").order_by("last_name", "first_name")
    )


def presenters(event) -> str:
    """The names of an event's presenters, members first, for a listing."""
    names = [u.get_full_name() for u in event.member_speakers.all()]
    names += [s.name for s in event.speakers.all() if s.public]
    return ", ".join(n for n in names if n)
