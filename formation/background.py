"""Single audited write path for a student's formation background."""

from __future__ import annotations

from . import notifications as notify_formation
from .models import BackgroundDetermination


def set_background(member, value, *, by, note="") -> BackgroundDetermination | None:
    """Set ``member``'s formation background to ``value`` (``clinical`` or
    ``academic``), recording an audit row and notifying the member. A no-op
    (returns None) when the value is unchanged."""
    profile = member.profile
    old = profile.formation_background
    if value == old:
        return None
    profile.formation_background = value
    profile.save(update_fields=["formation_background"])
    row = BackgroundDetermination.objects.create(
        member=member, background=value, previous=old, set_by=by,
        note=(note or "").strip(),
    )
    notify_formation.background_set(member, row)
    return row
