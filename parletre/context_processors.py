"""Template context for Parlêtre — the nav bell's unread count."""

from __future__ import annotations

from .models import Notification
from .permissions import is_member


def notifications(request):
    """Expose ``parletre_unread`` (count) and ``parletre_is_member`` to every
    template, so the nav can show the bell. Only queries for logged-in members.
    """
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and is_member(user):
        unread = Notification.objects.filter(
            recipient=user, read_at__isnull=True
        ).count()
        return {"parletre_is_member": True, "parletre_unread": unread}
    return {"parletre_is_member": False, "parletre_unread": 0}
