"""What the member's My LSP → Election tab shows (task #813)."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from . import ballots, eligibility, services
from .forms import BallotForm, NominationForm
from .models import Election, Nomination, VoterRollEntry

P = Election.Phase
#: How long the tab stays after the results (or the no-vote close).
SHOW_AFTER = timedelta(days=30)


#: Where the answer is kept on the user object, so one request asks once.
_MEMO = "_lsp_visible_election"
#: The session key holding a refused ballot's selections until it is redrawn.
DRAFT_KEY = "election_ballot_draft"


def visible_election_for(user):
    """The election this member's tab shows, or None. Runs on every page (the
    tab list feeds the avatar menu), so it stays cheap for non-voters, and
    is remembered on the user object, which lives for one request."""
    if not getattr(user, "is_authenticated", False):
        return None
    if not hasattr(user, _MEMO):
        setattr(user, _MEMO, _visible_election_for(user))
    return getattr(user, _MEMO)


def _visible_election_for(user):
    profile = getattr(user, "profile", None)
    has_role = profile is not None and profile.role in eligibility.VOTER_ROLES
    if not has_role and not (
        VoterRollEntry.objects.filter(user=user).exists()
        or Nomination.objects.filter(user=user).exists()
    ):
        return None
    election = services.current_election()
    if election is None or election.phase == P.DRAFT:
        return None
    ended = election.results_published_at or election.acclaimed_at
    if ended and timezone.now() - ended > SHOW_AFTER:
        return None
    if (eligibility.is_eligible_voter(user)
            or eligibility.is_on_roll(election, user)
            or election.nominations.filter(user=user).exists()):
        return election
    return None


def tab_context(request, election) -> dict:
    user = request.user
    phase = election.phase
    if phase == P.VOTING:
        services.ensure_roll_frozen(election)
    nomination = election.nominations.filter(user=user).first()
    slate_out = phase in (P.SLATE, P.VOTING, P.CLOSED, P.COUNTED, P.PUBLISHED, P.ACCLAIMED)
    candidates = ballots.candidates(election) if slate_out else []
    ctx = {
        "election": election,
        "phase": phase,
        "nomination": nomination,
        "decision_visible": slate_out,
        "may_stand": phase == P.NOMINATING and eligibility.may_stand(user),
        "nomination_form": NominationForm(
            initial={"letter": nomination.letter if nomination else ""}),
        "candidates": candidates,
    }
    if phase in (P.VOTING, P.CLOSED, P.COUNTED, P.PUBLISHED):
        ctx["on_roll"] = eligibility.is_on_roll(election, user)
        own = ballots.own_ballot(user, election)
        ctx["own_ballot"] = own
        if phase == P.VOTING and ctx["on_roll"]:
            draft = request.session.pop(DRAFT_KEY, None)
            if draft and draft.get("slug") == election.slug:
                # A ballot just refused for an error: show it as it was sent.
                ctx["editing"] = True
                ctx["ballot_form"] = BallotForm(candidates, draft.get("ranks", {}))
            else:
                ctx["editing"] = own is None or bool(request.GET.get("change"))
                ctx["ballot_form"] = BallotForm(
                    candidates, initial_order=[n.id for n in own or []])
    if phase == P.VOTING and election.show_during_voting == Election.DuringVoting.TURNOUT:
        ctx["turnout"] = ballots.turnout(election)
        ctx["roll_size"] = len(services.roll_ids(election))
    if phase == P.PUBLISHED:
        result = election.count_result or {}
        names = result.get("names", {})
        ctx["winners"] = [names.get(str(i), "") for i in result.get("elected", [])]
        if election.show_results == Election.ResultsShown.FULL:
            ctx["result"] = result
            ctx["stages"] = [{
                **s,
                "subject_name": names.get(str(s["subject"]), "") if s.get("subject") else "",
                "rows": [(names.get(cid, cid), v) for cid, v in s["totals"].items()],
            } for s in result.get("stages", [])]
    if phase == P.ACCLAIMED:
        ctx["winners"] = [n.name for n in candidates]
    return ctx
