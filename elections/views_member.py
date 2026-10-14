"""The member's election actions (task #813). Each is a POST from the My LSP
→ Election tab and returns there."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import ballots, services
from .forms import BallotForm, NominationForm
from .models import Election, Nomination
from .queries import DRAFT_KEY


def _tab():
    return redirect(reverse("formation:formation") + "?tab=election")


@require_POST
@login_required
def nominate(request, slug):
    election = get_object_or_404(Election, slug=slug)
    form = NominationForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please write a motivation letter.")
        return _tab()
    try:
        services.submit_nomination(election, request.user, form.cleaned_data["letter"])
    except services.ElectionError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Your nomination is in. You can edit or withdraw it "
                                  "until nominations close.")
    return _tab()


@require_POST
@login_required
def withdraw(request, slug):
    nomination = get_object_or_404(Nomination, election__slug=slug, user=request.user)
    try:
        services.withdraw_nomination(nomination)
    except services.ElectionError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Your nomination is withdrawn.")
    return _tab()


@require_POST
@login_required
def ballot(request, slug):
    election = get_object_or_404(Election, slug=slug)
    form = BallotForm(ballots.candidates(election), request.POST)
    if not form.is_valid():
        errors = form.non_field_errors() or ["That ballot couldn't be recorded."]
        messages.error(request, errors[0])
        # Keep the selections for the redraw (read once, then dropped), so
        # one duplicate rank doesn't cost the voter their whole ballot.
        request.session[DRAFT_KEY] = {
            "slug": election.slug,
            "ranks": {k: v for k, v in request.POST.items() if k.startswith("rank_")},
        }
        return redirect(reverse("formation:formation") + "?tab=election&change=1")
    try:
        services.cast_ballot(election, request.user, form.ranked_ids())
    except services.ElectionError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Your ballot was recorded. You can change it until "
                                  "voting closes.")
    return _tab()
