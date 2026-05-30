"""Per-request timezone middleware.

Activates the authenticated user's ``Profile.timezone`` for the duration
of the request so Django's ``localtime`` filter and ``{{ datetime }}``
template renders happen in their preferred zone. Falls back to project
``TIME_ZONE`` (Pacific) when there's no user or no preference set.

Place after ``AuthenticationMiddleware`` in ``settings.MIDDLEWARE`` so
``request.user`` is available.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone


class TimezoneMiddleware:
    """Activate user.profile.timezone for the request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tz_name = ""
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            tz_name = getattr(getattr(user, "profile", None), "timezone", "") or ""
        if tz_name:
            try:
                timezone.activate(ZoneInfo(tz_name))
            except ZoneInfoNotFoundError:
                timezone.deactivate()
        else:
            timezone.deactivate()
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()
