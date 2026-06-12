"""Bearer-token authentication + authorization for the dev API.

``@dev_api(permission=…)`` wraps a view so it:

1. reads ``Authorization: Bearer <token>``, resolves it to a :class:`DevApiToken`
   (401 if missing/unknown/revoked),
2. enforces ``permission(user)`` on the token's bound user (403 otherwise),
3. exposes the authenticated user as ``request.api_user``.

Token auth carries no cookies, so the views are CSRF-exempt. The whole surface
can be killed with ``DEVAPI_ENABLED=False`` (503), independent of the
member-facing ``SUGGESTIONS_ENABLED`` flag — the dev needs API access before
the suggestion box opens to members.
"""

from __future__ import annotations

from functools import wraps

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from suggestions.permissions import can_triage_suggestions

from .models import DevApiToken


def _bearer(request) -> str:
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if header.startswith("Bearer "):
        return header[len("Bearer ") :].strip()
    return ""


def dev_api(permission=can_triage_suggestions):
    """Decorator: authenticate a bearer token and authorize via ``permission``."""

    def decorator(view):
        @csrf_exempt
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not getattr(settings, "DEVAPI_ENABLED", True):
                return JsonResponse({"error": "devapi_disabled"}, status=503)
            token = DevApiToken.authenticate(_bearer(request))
            if token is None:
                return JsonResponse({"error": "unauthorized"}, status=401)
            user = token.user
            if user is None or not user.is_active:
                return JsonResponse({"error": "unauthorized"}, status=401)
            if not permission(user):
                return JsonResponse({"error": "forbidden"}, status=403)
            request.api_user = user
            request.api_token = token
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
