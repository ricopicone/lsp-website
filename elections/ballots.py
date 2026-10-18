"""The ONLY reader of ballot rankings (task #813).

A ballot is anonymous and final (the Board's decision, 2026-10-14): it
carries no voter and no time, and a separate VoteRecord says only who has
voted. One exit for rankings, ``anonymous_ballots`` for the counter (order
shuffled). Everything else may ask only who has voted (``voted_user_ids``,
``has_voted``, ``turnout``). A source-scan test pins that no other
module references BallotRanking, so secrecy holds by structure rather than
by remembering.
"""

from __future__ import annotations

import random

from django.db import IntegrityError, transaction

from .models import Ballot, BallotRanking, Nomination, VoteRecord


def candidates(election) -> list[Nomination]:
    """The slate: accepted, not withdrawn."""
    return list(
        election.nominations
        .filter(status=Nomination.Status.ACCEPTED, withdrawn_at__isnull=True)
        .select_related("user")
        .order_by("user__last_name", "user__first_name")
    )


class AlreadyVoted(ValueError):
    pass


def cast(election, voter, ranked: list[int]) -> Ballot:
    """Record that ``voter`` voted and store their ranking (nomination ids,
    first choice first) as an anonymous ballot, in one transaction. Raises
    AlreadyVoted on a second ballot, and ValueError on an empty ballot, a
    repeated candidate, or an id not on this election's slate."""
    allowed = {n.id for n in candidates(election)}
    if not ranked or len(set(ranked)) != len(ranked) or not set(ranked) <= allowed:
        raise ValueError("A ballot must rank at least one candidate, each once.")
    try:
        with transaction.atomic():
            VoteRecord.objects.create(election=election, voter=voter)
            ballot = Ballot.objects.create(election=election)
            BallotRanking.objects.bulk_create(
                BallotRanking(ballot=ballot, nomination_id=nid, rank=i)
                for i, nid in enumerate(ranked, start=1)
            )
    except IntegrityError as exc:
        raise AlreadyVoted("You have already voted; a ballot can't be changed.") from exc
    return ballot


def has_voted(user, election) -> bool:
    return VoteRecord.objects.filter(election=election, voter=user).exists()


def voted_user_ids(election) -> set[int]:
    return set(VoteRecord.objects.filter(election=election)
               .values_list("voter_id", flat=True))


def turnout(election) -> int:
    return VoteRecord.objects.filter(election=election).count()


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
