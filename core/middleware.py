"""Impersonation ("View as") middleware.

A superuser may view the site as another user (personas for safe testing, or a
real member for support). While impersonating:

- ``request.user`` is the target; ``request.impersonator`` is the real superuser.
- Impersonating a *real* member is **read-only** — unsafe HTTP methods are
  blocked (writes can't alter their data or act as them). *Personas*
  (``Profile.is_persona``) are fully writable.

Security: the swap only happens when the *authenticated* user (before the swap)
is a superuser; the session flag alone is never trusted. Must run after
``AuthenticationMiddleware`` and ``MessageMiddleware``.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import redirect

SESSION_KEY = "impersonate_user_id"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class ImpersonationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.impersonator = None
        request.impersonation_readonly = False

        target_id = request.session.get(SESSION_KEY)
        real_user = getattr(request, "user", None)

        if target_id and real_user is not None and real_user.is_authenticated:
            # Never trust the session flag alone — only a real superuser swaps.
            if not real_user.is_superuser:
                request.session.pop(SESSION_KEY, None)
            else:
                target = (
                    get_user_model().objects
                    .filter(pk=target_id, is_active=True)
                    .select_related("profile").first()
                )
                if target is None or target.is_superuser:
                    request.session.pop(SESSION_KEY, None)
                else:
                    request.impersonator = real_user
                    request.user = target
                    request.impersonation_readonly = not getattr(
                        getattr(target, "profile", None), "is_persona", False
                    )
                    if (request.impersonation_readonly
                            and request.method not in SAFE_METHODS
                            and not request.path.startswith("/impersonate/")):
                        messages.error(
                            request,
                            "You're viewing as a real member (read-only) — "
                            "writes are blocked. Exit impersonation to act as "
                            "yourself.",
                        )
                        return redirect(request.META.get("HTTP_REFERER") or "/")

        return self.get_response(request)
