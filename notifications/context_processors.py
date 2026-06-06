"""Template context for the site-wide nav bell."""

from __future__ import annotations

from .models import Notification


def bell(request):
    """Expose ``notifications_unread`` (count) to every template so the nav can
    render the bell for any signed-in member."""
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        unread = Notification.objects.filter(
            recipient=user, read_at__isnull=True
        ).count()
        return {"notifications_unread": unread}
    return {"notifications_unread": 0}
