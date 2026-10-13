"""Board review of nominations, /admin-tools/board/elections/ (task #813).

The bylaws give candidacy review to the Board (Art. 3 §1), so this lives in
the Board's admin area, not the Election Administrator's. Board members see
nominations and decide them; they see nothing about the voter roll.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import services
from .models import Nomination
from .permissions import can_review_nominations


def _gate(request):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if not can_review_nominations(request.user):
        raise Http404
    return None


def review(request):
    denied = _gate(request)
    if denied:
        return denied
    election = services.current_election()
    nominations = []
    if election is not None:
        nominations = (election.nominations.filter(withdrawn_at__isnull=True)
                       .select_related("user", "reviewed_by"))
    return render(request, "elections/board/review.html", {
        "election": election,
        "phase": election.phase if election else None,
        "nominations": nominations,
        "statuses": [Nomination.Status.ACCEPTED, Nomination.Status.DECLINED],
    })


@require_POST
def decide(request, pk):
    denied = _gate(request)
    if denied:
        return denied
    nomination = get_object_or_404(Nomination.objects.select_related("election", "user"), pk=pk)
    try:
        services.review_nomination(nomination, request.user,
                                   request.POST.get("status", ""), request.POST.get("note", ""))
    except services.ElectionError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"{nomination.name}: {nomination.get_status_display().lower()}.")
    return redirect("elections:board_review")
