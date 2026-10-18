"""One vote, unlinked from the voter (the Board's decision, 2026-10-14).

A ballot carries no voter and no time; a separate VoteRecord says only that
someone voted. So a ballot can't be traced to a voter even in the database,
and it can't be changed once cast.
"""

import pytest
from django.urls import reverse

from elections import ballots, services
from elections.models import Ballot, VoteRecord
from elections.tests.factories import make_election, make_member, make_nomination

pytestmark = pytest.mark.django_db


def _voting(n=2):
    """An open vote, and a voter who is on its frozen roll."""
    e = make_election("voting")
    noms = [make_nomination(e) for _ in range(n)]
    voter = make_member()
    services.ensure_roll_frozen(e)
    return e, noms, voter


def test_a_ballot_carries_no_voter_and_no_time():
    names = {f.name for f in Ballot._meta.get_fields()}
    assert not names & {"voter", "voter_id", "cast_at", "updated_at", "created_at"}


def test_ballot_ids_do_not_reveal_the_order_of_voting():
    from django.db.models import UUIDField
    assert isinstance(Ballot._meta.pk, UUIDField)


def test_casting_records_the_vote_and_an_anonymous_ballot():
    e, (a, b), voter = _voting()
    services.cast_ballot(e, voter, [b.id, a.id])
    assert VoteRecord.objects.filter(election=e, voter=voter).exists()
    assert ballots.voted_user_ids(e) == {voter.id}
    assert ballots.turnout(e) == 1
    assert ballots.anonymous_ballots(e) == [[b.id, a.id]]


def test_a_second_ballot_is_refused_and_the_first_stands():
    e, (a, b), voter = _voting()
    services.cast_ballot(e, voter, [a.id])
    with pytest.raises(services.ElectionError, match="already voted"):
        services.cast_ballot(e, voter, [b.id])
    assert ballots.anonymous_ballots(e) == [[a.id]]
    assert Ballot.objects.filter(election=e).count() == 1


def test_a_refused_ballot_records_no_vote():
    e, (a, _b), voter = _voting()
    with pytest.raises(services.ElectionError):
        services.cast_ballot(e, voter, [a.id, a.id])
    assert not VoteRecord.objects.exists() and not Ballot.objects.exists()


def test_after_voting_the_tab_says_recorded_and_offers_no_ballot(client):
    e, (a, _b), voter = _voting()
    client.force_login(voter)
    client.post(reverse("elections:ballot", args=[e.slug]), {f"rank_{a.id}": "1"})
    html = client.get(reverse("formation:formation") + "?tab=election").content.decode()
    assert "Your ballot is recorded" in html
    assert reverse("elections:ballot", args=[e.slug]) not in html
    assert "Change my ballot" not in html


def test_the_ballot_form_says_it_is_final(client):
    e, _, voter = _voting()
    client.force_login(voter)
    html = client.get(reverse("formation:formation") + "?tab=election").content.decode()
    assert "is final and can't be changed" in html
