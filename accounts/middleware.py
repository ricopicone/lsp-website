"""Per-request timezone middleware.

Activates the authenticated user's ``Profile.timezone`` for the duration
of the request so Django's ``localtime`` filter and ``{{ datetime }}``
template renders happen in their preferred zone. Falls back to project
``TIME_ZONE`` (Pacific) when there's no user or no preference set.

Place after ``AuthenticationMiddleware`` in ``settings.MIDDLEWARE`` so
``request.user`` is available.
"""

from __future__ import annotations

from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.shortcuts import redirect
from django.urls import Resolver404, resolve, reverse
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


class TwoFactorEnforcementMiddleware:
    """Force admins through TOTP enrollment + a per-session challenge.

    Ships behind ``settings.TWO_FACTOR_ENFORCED`` (default off) so the
    enrollment/verify flows can be opted into without blocking current
    testers. When on, any authenticated user for whom
    ``accounts.twofactor.requires_2fa`` is true must, before reaching any
    non-exempt page:

    1. enroll an authenticator (redirected to ``twofactor_setup``), then
    2. clear the challenge once per session (redirected to ``twofactor_verify``).

    Skipped while impersonating — the real admin (``request.impersonator``)
    already verified for their own session.

    Place after ``AuthenticationMiddleware`` and ``ImpersonationMiddleware``
    so ``request.user`` / ``request.impersonator`` are set.
    """

    #: URL names always reachable while unverified (the auth/2FA flows + exits).
    EXEMPT_NAMES = frozenset({
        "login", "logout", "signup",
        "password_reset", "password_reset_done",
        "password_reset_confirm", "password_reset_complete",
        "magic_link_request", "magic_link_consume",
        "twofactor_setup", "twofactor_verify",
        "twofactor_recovery", "twofactor_disable",
        "admin:logout",
    })

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._should_enforce(request):
            redirect_response = self._enforce(request)
            if redirect_response is not None:
                return redirect_response
        return self.get_response(request)

    def _should_enforce(self, request) -> bool:
        from .twofactor import enforcement_on, requires_2fa

        if not enforcement_on():
            return False
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        # The real admin already verified; don't challenge the impersonated user.
        if getattr(request, "impersonator", None) is not None:
            return False
        return requires_2fa(user)

    def _is_exempt_path(self, request) -> bool:
        from django.conf import settings

        path = request.path_info
        for prefix in (settings.STATIC_URL, getattr(settings, "MEDIA_URL", None)):
            if prefix and path.startswith(prefix):
                return True
        try:
            match = resolve(path)
        except Resolver404:
            return False
        return match.view_name in self.EXEMPT_NAMES

    def _enforce(self, request):
        from .twofactor import SESSION_VERIFIED_KEY, has_confirmed_device

        if self._is_exempt_path(request):
            return None
        if not has_confirmed_device(request.user):
            return redirect("twofactor_setup")
        if not request.session.get(SESSION_VERIFIED_KEY):
            nxt = quote(request.get_full_path())
            return redirect(f"{reverse('twofactor_verify')}?next={nxt}")
        return None
