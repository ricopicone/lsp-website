"""Member + staff views for the suggestion box.

Members file suggestions from the floating widget (``submit``, fetch/JSON) or the
standalone page (``suggest_page``), and review their own under ``mine``. Site
staff triage everything from ``triage`` (mounted at ``/admin-tools/suggestions/``).
Screenshots live in the private bucket and are served only to the submitter or a
triager via ``screenshot_download``.
"""

from __future__ import annotations

import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import notifications as notify_suggestions
from .forms import SuggestionForm
from .models import Suggestion
from .permissions import can_submit_suggestion, can_triage_suggestions


def _feature_on() -> bool:
    return getattr(settings, "SUGGESTIONS_ENABLED", False)


def _wants_json(request) -> bool:
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _require_member(request) -> None:
    if not (_feature_on() and can_submit_suggestion(request.user)):
        raise PermissionDenied


def _save(form, request) -> Suggestion:
    suggestion = form.save(commit=False)
    suggestion.submitted_by = request.user
    suggestion.context = _capture_context(request)
    suggestion.save()
    url = request.build_absolute_uri(reverse("suggestions_triage"))
    notify_suggestions.filed(suggestion, url)
    return suggestion


def _capture_context(request) -> dict:
    """Merge the widget's client-side context (JSON in a hidden field) with the
    user-agent the server sees. Never trust the blob to be valid JSON."""
    raw = request.POST.get("context") or ""
    data: dict = {}
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                data = parsed
        except (ValueError, TypeError):
            pass
    data.setdefault("user_agent", request.META.get("HTTP_USER_AGENT", "")[:500])
    return data


@login_required
def suggest_page(request):
    """The standalone /suggestions/ form (not anchored to a page)."""
    _require_member(request)
    if request.method == "POST":
        form = SuggestionForm(request.POST, request.FILES)
        if form.is_valid():
            _save(form, request)
            messages.success(request, "Thanks — your suggestion was sent to the site team.")
            return redirect("suggestions:mine")
    else:
        form = SuggestionForm()
    return render(request, "suggestions/suggest.html", {"form": form})


@login_required
@require_POST
def submit(request):
    """Widget endpoint: accepts a fetch POST (JSON reply) and is the non-JS
    fallback target for the widget form."""
    if not (_feature_on() and can_submit_suggestion(request.user)):
        if _wants_json(request):
            return JsonResponse({"ok": False, "error": "forbidden"}, status=403)
        raise PermissionDenied
    form = SuggestionForm(request.POST, request.FILES)
    if form.is_valid():
        suggestion = _save(form, request)
        if _wants_json(request):
            return JsonResponse({"ok": True, "id": suggestion.pk})
        messages.success(request, "Thanks — your suggestion was sent to the site team.")
        return redirect("suggestions:mine")
    if _wants_json(request):
        return JsonResponse({"ok": False, "errors": form.errors}, status=400)
    return render(request, "suggestions/suggest.html", {"form": form}, status=400)


@login_required
def mine(request):
    """Legacy ``/suggestions/mine/`` — now the My LSP hub's Suggestions tab."""
    from django.urls import reverse

    return redirect(reverse("formation:formation") + "?tab=suggestions")


@login_required
def screenshot_download(request, pk):
    suggestion = get_object_or_404(Suggestion, pk=pk)
    if not (
        suggestion.submitted_by_id == request.user.id
        or can_triage_suggestions(request.user)
    ):
        raise Http404
    if not suggestion.screenshot:
        raise Http404
    filename = suggestion.screenshot.name.rsplit("/", 1)[-1]
    return FileResponse(suggestion.screenshot.open("rb"), filename=filename)


@login_required
def triage(request):
    """Staff queue at /admin-tools/suggestions/."""
    if not can_triage_suggestions(request.user):
        raise PermissionDenied

    if request.method == "POST":
        suggestion = get_object_or_404(Suggestion, pk=request.POST.get("pk"))
        new_status = request.POST.get("status", suggestion.status)
        status_changed = new_status != suggestion.status
        if new_status in Suggestion.Status.values:
            suggestion.status = new_status
        priority = request.POST.get("priority", "")
        suggestion.priority = priority if priority in Suggestion.Priority.values else ""
        suggestion.staff_notes = request.POST.get("staff_notes", suggestion.staff_notes)
        suggestion.reviewed_by = request.user
        suggestion.reviewed_at = timezone.now()
        suggestion.save()
        if status_changed:
            url = request.build_absolute_uri(reverse("suggestions:mine"))
            notify_suggestions.status_changed(suggestion, url)
        messages.success(request, f"Updated suggestion #{suggestion.pk}.")
        return redirect(f"{reverse('suggestions_triage')}?{request.GET.urlencode()}")

    qs = Suggestion.objects.select_related("submitted_by")
    status = request.GET.get("status", "")
    kind = request.GET.get("kind", "")
    if status in Suggestion.Status.values:
        qs = qs.filter(status=status)
    elif status == "open":
        qs = qs.filter(status__in=Suggestion.ACTIONABLE_STATUSES)
    if kind in Suggestion.Kind.values:
        qs = qs.filter(kind=kind)

    return render(request, "suggestions/triage.html", {
        "suggestions": qs,
        "status_filter": status,
        "kind_filter": kind,
        "status_choices": Suggestion.Status.choices,
        "kind_choices": Suggestion.Kind.choices,
        "priority_choices": Suggestion.Priority.choices,
        "open_count": Suggestion.objects.filter(
            status__in=Suggestion.ACTIONABLE_STATUSES
        ).count(),
    })
