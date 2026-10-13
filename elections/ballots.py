"""The ONLY reader of ballot rankings (task #813).

Two exits: ``own_ballot`` for the voter's own page, and
``anonymous_ballots`` for the counter (voter dropped, order shuffled).
Everything else may ask only whether a Ballot row exists
(``voted_user_ids``, ``turnout``). A source-scan test pins that no other
module references BallotRanking, so secrecy holds by structure rather than
by remembering.
"""

from __future__ import annotations

import random

from django.db import transaction

from .models import Ballot, BallotRanking, Nomination


def candidates(election) -> list[Nomination]:
    """The slate: accepted, not withdrawn."""
    return list(
        election.nominations
        .filter(status=Nomination.Status.ACCEPTED, withdrawn_at__isnull=True)
        .select_related("user")
        .order_by("user__last_name", "user__first_name")
    )


def cast(election, voter, ranked: list[int]) -> Ballot:
    """Record ``voter``'s ballot (nomination ids, first choice first),
    replacing any earlier one. Raises ValueError on an empty ballot, a
    repeated candidate, or an id not on this election's slate."""
    allowed = {n.id for n in candidates(election)}
    if not ranked or len(set(ranked)) != len(ranked) or not set(ranked) <= allowed:
        raise ValueError("A ballot must rank at least one candidate, each once.")
    with transaction.atomic():
        ballot, _ = Ballot.objects.select_for_update().get_or_create(
            election=election, voter=voter,
        )
        BallotRanking.objects.filter(ballot=ballot).delete()
        BallotRanking.objects.bulk_create(
            BallotRanking(ballot=ballot, nomination_id=nid, rank=i)
            for i, nid in enumerate(ranked, start=1)
        )
        ballot.save(update_fields=["updated_at"])
    return ballot


def own_ballot(user, election) -> list[Nomination] | None:
    """The voter's own ranking, first choice first; None if they haven't voted."""
    ballot = Ballot.objects.filter(election=election, voter=user).first()
    if ballot is None:
        return None
    return [
        r.nomination for r in
        BallotRanking.objects.filter(ballot=ballot)
        .select_related("nomination__user").order_by("rank")
    ]


def voted_user_ids(election) -> set[int]:
    return set(Ballot.objects.filter(election=election).values_list("voter_id", flat=True))


def turnout(election) -> int:
    return Ballot.objects.filter(election=election).count()


def anonymous_ballots(election) -> list[list[int]]:
    """Every ballot as a list of nomination ids in rank order, no voter, shuffled."""
    by_ballot: dict[int, list[tuple[int, int]]] = {}
    rows = (BallotRanking.objects.filter(ballot__election=election)
            .values_list("ballot_id", "rank", "nomination_id"))
    for ballot_id, rank, nid in rows:
        by_ballot.setdefault(ballot_id, []).append((rank, nid))
    out = [[nid for _, nid in sorted(r)] for r in by_ballot.values()]
    random.SystemRandom().shuffle(out)
    return out
