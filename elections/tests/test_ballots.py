"""Casting, changing and reading a ballot (task #813)."""

import pytest

from elections import ballots
from elections.forms import BallotForm
from elections.tests.factories import make_election, make_member, make_nomination

pytestmark = pytest.mark.django_db


def _setup():
    e = make_election("voting")
    a, b = make_nomination(e), make_nomination(e)
    declined = make_nomination(e, status="declined")
    return e, a, b, declined


def test_cast_and_read_own():
    e, a, b, _ = _setup()
    v = make_member()
    ballots.cast(e, v, [b.id, a.id])
    assert [n.id for n in ballots.own_ballot(v, e)] == [b.id, a.id]
    assert ballots.voted_user_ids(e) == {v.id}
    assert ballots.turnout(e) == 1


def test_changing_replaces():
    e, a, b, _ = _setup()
    v = make_member()
    ballots.cast(e, v, [a.id, b.id])
    ballots.cast(e, v, [b.id])
    assert [n.id for n in ballots.own_ballot(v, e)] == [b.id]
    assert ballots.anonymous_ballots(e) == [[b.id]]
    assert ballots.turnout(e) == 1


def test_own_ballot_is_none_before_voting():
    e, *_ = _setup()
    assert ballots.own_ballot(make_member(), e) is None


def test_withdrawn_candidate_is_not_a_candidate():
    from django.utils import timezone
    e, a, b, _ = _setup()
    b.withdrawn_at = timezone.now()
    b.save()
    assert [n.id for n in ballots.candidates(e)] == [a.id]


@pytest.mark.parametrize("bad", ["empty", "dup", "declined", "other"])
def test_cast_rejects(bad):
    e, a, b, declined = _setup()
    other = make_nomination(make_election("voting"))
    ranked = {"empty": [], "dup": [a.id, a.id], "declined": [declined.id],
              "other": [other.id]}[bad]
    with pytest.raises(ValueError):
        ballots.cast(e, make_member(), ranked)
    assert ballots.turnout(e) == 0


def test_form_orders_by_rank_and_closes_gaps():
    e, a, b, _ = _setup()
    f = BallotForm(ballots.candidates(e), data={f"rank_{a.id}": "2", f"rank_{b.id}": "1"})
    assert f.is_valid(), f.errors
    assert f.ranked_ids() == [b.id, a.id]
    gap = BallotForm(ballots.candidates(e), data={f"rank_{a.id}": "2"})
    assert gap.is_valid(), gap.errors
    assert gap.ranked_ids() == [a.id]


def test_form_refuses_duplicate_rank_and_empty():
    e, a, b, _ = _setup()
    dup = BallotForm(ballots.candidates(e), data={f"rank_{a.id}": "1", f"rank_{b.id}": "1"})
    assert not dup.is_valid()
    assert not BallotForm(ballots.candidates(e), data={}).is_valid()


def test_form_prefills_existing_order():
    e, a, b, _ = _setup()
    f = BallotForm(ballots.candidates(e), initial_order=[b.id, a.id])
    assert f.fields[f"rank_{b.id}"].initial == "1"
    assert f.fields[f"rank_{a.id}"].initial == "2"
