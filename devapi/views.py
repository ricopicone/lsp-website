"""Dev API endpoints.

A small, token-authenticated JSON surface for the web developer (a Claude Code
session) to read and triage the work the site produces. Today that's the member
suggestion queue; the shape (``@dev_api`` + JSON in/out) is meant to grow into a
broader admin surface — see the module README for the planned feature set.

Writes go through the *same* code path as the human triage view
(:func:`suggestions.views.triage`): status is validated against the choices,
``reviewed_by``/``reviewed_at`` are stamped to the token's user, and a status
change notifies the submitter. The API never does more than the web UI does.
"""

from __future__ import annotations

import datetime as dt
import json

from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from suggestions import notifications as notify_suggestions
from suggestions.models import Suggestion

from .auth import dev_api
from .serializers import suggestion_detail, suggestion_summary


def _json_body(request) -> dict:
    if not request.body:
        return {}
    try:
        data = json.loads(request.body)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


@dev_api()
@require_http_methods(["GET"])
def whoami(request):
    """Connectivity + identity check: which user/roles this token acts as."""
    user = request.api_user
    return JsonResponse(
        {
            "user": {"id": user.pk, "name": user.get_full_name() or "", "email": user.email},
            "staff_roles": list(user.staff_roles.values_list("key", flat=True)),
            "is_superuser": user.is_superuser,
            "token_label": request.api_token.label,
        }
    )


@dev_api()
@require_http_methods(["GET"])
def suggestion_list(request):
    """List suggestions, newest first.

    Query params: ``status`` (a status value, or ``open`` for the actionable
    set), ``kind``, ``priority``, ``since`` (YYYY-MM-DD, created on/after),
    ``limit`` (default 50, max 200).
    """
    qs = Suggestion.objects.select_related("submitted_by")

    status = request.GET.get("status", "")
    if status == "open":
        qs = qs.filter(status__in=Suggestion.ACTIONABLE_STATUSES)
    elif status in Suggestion.Status.values:
        qs = qs.filter(status=status)
    elif status:
        return JsonResponse({"error": f"unknown status: {status}"}, status=400)

    kind = request.GET.get("kind", "")
    if kind:
        if kind not in Suggestion.Kind.values:
            return JsonResponse({"error": f"unknown kind: {kind}"}, status=400)
        qs = qs.filter(kind=kind)

    priority = request.GET.get("priority", "")
    if priority:
        if priority not in Suggestion.Priority.values:
            return JsonResponse({"error": f"unknown priority: {priority}"}, status=400)
        qs = qs.filter(priority=priority)

    since = request.GET.get("since", "")
    if since:
        try:
            day = dt.datetime.strptime(since, "%Y-%m-%d").date()
        except ValueError:
            return JsonResponse({"error": "since must be YYYY-MM-DD"}, status=400)
        start = timezone.make_aware(dt.datetime.combine(day, dt.time.min))
        qs = qs.filter(created_at__gte=start)

    try:
        limit = min(max(int(request.GET.get("limit", 50)), 1), 200)
    except (TypeError, ValueError):
        limit = 50

    rows = list(qs[:limit])
    return JsonResponse(
        {
            "count": len(rows),
            "results": [suggestion_summary(s) for s in rows],
        }
    )


@dev_api()
@require_http_methods(["GET", "POST"])
def suggestion_detail_view(request, pk: int):
    """GET full detail; POST triage updates (status / priority / staff_notes)."""
    try:
        s = Suggestion.objects.select_related("submitted_by", "reviewed_by").get(pk=pk)
    except Suggestion.DoesNotExist:
        return JsonResponse({"error": "not found"}, status=404)

    if request.method == "GET":
        return JsonResponse(suggestion_detail(s))

    body = _json_body(request)
    changed_fields: list[str] = []
    status_changed = False

    if "status" in body:
        new_status = body["status"]
        if new_status not in Suggestion.Status.values:
            return JsonResponse({"error": f"unknown status: {new_status}"}, status=400)
        if new_status != s.status:
            s.status = new_status
            status_changed = True
        changed_fields.append("status")

    if "priority" in body:
        new_priority = body["priority"] or ""
        if new_priority and new_priority not in Suggestion.Priority.values:
            return JsonResponse({"error": f"unknown priority: {new_priority}"}, status=400)
        s.priority = new_priority
        changed_fields.append("priority")

    if "staff_notes" in body:
        s.staff_notes = body["staff_notes"] or ""
        changed_fields.append("staff_notes")

    if not changed_fields:
        return JsonResponse(
            {"error": "nothing to update (send status, priority, or staff_notes)"},
            status=400,
        )

    s.reviewed_by = request.api_user
    s.reviewed_at = timezone.now()
    s.save()

    if status_changed:
        url = request.build_absolute_uri(reverse("suggestions:mine"))
        notify_suggestions.status_changed(s, url)

    return JsonResponse(suggestion_detail(s))


@dev_api()
@require_http_methods(["GET"])
def suggestion_stats(request):
    """Counts by status and kind, plus the open total."""
    from django.db.models import Count

    by_status = {
        r["status"]: r["n"]
        for r in Suggestion.objects.values("status").annotate(n=Count("pk"))
    }
    by_kind = {
        r["kind"]: r["n"]
        for r in Suggestion.objects.values("kind").annotate(n=Count("pk"))
    }
    return JsonResponse(
        {
            "total": Suggestion.objects.count(),
            "open": Suggestion.objects.filter(
                status__in=Suggestion.ACTIONABLE_STATUSES
            ).count(),
            "by_status": by_status,
            "by_kind": by_kind,
        }
    )
