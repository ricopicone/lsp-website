"""Vote counting, pure (task #813). Every STV case here is worked by hand in
its comment, and asserts the stages as well as the winners."""

import random
from decimal import Decimal

from elections import counting


def stv(ballots, cands, seats, seed=1):
    return counting.count_stv(ballots, cands, seats, random.Random(seed))


def test_quota_and_first_stage_election():
    # 10 ballots, 2 seats: quota floor(10/3)+1 = 4. A has 6 at stage 1.
    b = [[1, 2]] * 6 + [[2]] * 3 + [[3]] * 1
    r = stv(b, [1, 2, 3], 2)
    assert r["quota"] == "4"
    assert r["valid_ballots"] == 10
    assert r["elected"][0] == 1
    assert r["stages"][0]["totals"] == {"1": "6", "2": "3", "3": "1"}


def test_surplus_transfers_fractionally_and_truncates():
    # A's surplus is 6-4 = 2, so each of A's six ballots moves at 2/6, which
    # truncates to 0.33333; B ends on 3 + 6 x 0.33333 = 4.99998 >= 4.
    b = [[1, 2]] * 6 + [[2]] * 3 + [[3]] * 1
    r = stv(b, [1, 2, 3], 2)
    transfer = next(s for s in r["stages"] if s["action"] == "surplus")
    assert transfer["subject"] == 1
    assert transfer["totals"]["1"] == "4"
    assert transfer["totals"]["2"] == "4.99998"
    assert r["elected"] == [1, 2]


def test_exclusion_transfers_at_current_value():
    # 9 ballots, 1 seat, quota 5. Nobody reaches it; C (lowest) is excluded
    # and both of C's ballots go on to B, who reaches 5.
    b = [[1]] * 4 + [[2]] * 3 + [[3, 2]] * 2
    r = stv(b, [1, 2, 3], 1)
    assert [s["subject"] for s in r["stages"] if s["action"] == "exclude"] == [3]
    assert r["stages"][-1]["totals"]["2"] == "5"
    assert r["elected"] == [2]


def test_exhausted_ballots_counted():
    # No ballot has a second preference: excluding C exhausts 2, then B 3.
    b = [[1]] * 4 + [[2]] * 3 + [[3]] * 2
    r = stv(b, [1, 2, 3], 1)
    assert Decimal(r["stages"][-1]["exhausted"]) == Decimal(5)
    assert r["elected"] == [1]


def test_remaining_equals_seats_elects_all():
    # Quota for 4 ballots and 3 seats is 2: A is elected, then B and C are
    # the only continuing candidates for the two seats left.
    b = [[1]] * 2 + [[2]] * 1 + [[3]] * 1
    r = stv(b, [1, 2, 3], 3)
    assert sorted(r["elected"]) == [1, 2, 3]
    assert r["lots"] == []


def test_tie_broken_by_earlier_stage():
    # 13 ballots, 1 seat, quota 7. Stage 1: A5 B3 C4 D1. D is excluded and
    # its ballot goes to B, so stage 2 is A5 B4 C4. B and C tie for
    # exclusion; at stage 1 B had fewer, so B goes, with no lot drawn.
    b = [[1]] * 5 + [[2]] * 3 + [[3]] * 4 + [[4, 2]] * 1
    r = stv(b, [1, 2, 3, 4], 1)
    assert r["excluded"][:2] == [4, 2]
    assert r["lots"] == []


def test_tie_by_lot_is_recorded_and_seed_reproducible():
    # Quota 3; B and C tie on 1 at the first stage, with nothing earlier to
    # break it, so a lot is drawn and recorded.
    b = [[1]] * 2 + [[2]] * 1 + [[3]] * 1
    r1 = stv(b, [1, 2, 3], 1, seed=7)
    r2 = stv(b, [1, 2, 3], 1, seed=7)
    assert r1["lots"] and r1["lots"][0]["tied"] == [2, 3]
    assert r1 == r2
    assert r1["elected"] == [1]


def test_partial_ballots_and_unranked_candidates():
    b = [[2]] * 3 + [[1, 3]] * 2
    r = stv(b, [1, 2, 3], 1)
    assert r["elected"] == [2]


def test_ballot_naming_no_candidate_is_not_valid():
    r = stv([[9]] + [[1]] * 2, [1, 2], 1)
    assert r["valid_ballots"] == 2


def test_top_n_counts_each_ballots_top_seats():
    # Top two of each ballot: 1 gets 3, 2 gets 3 + 2 = 5, 3 gets 2.
    b = [[1, 2, 3]] * 3 + [[3, 2, 1]] * 2
    r = counting.count_top_n(b, [1, 2, 3], 2, random.Random(1))
    assert r["elected"] == [2, 1]
    assert r["stages"][0]["totals"] == {"1": "3", "2": "5", "3": "2"}


def test_top_n_tie_for_last_seat_by_lot():
    b = [[1, 2]] * 2 + [[1, 3]] * 2
    r = counting.count_top_n(b, [1, 2, 3], 2, random.Random(3))
    assert r["elected"][0] == 1
    assert r["lots"] and r["lots"][0]["tied"] == [2, 3]


def test_count_dispatch_records_seed():
    r = counting.count("stv", [[1]], [1, 2], 1, seed=42)
    assert r["seed"] == 42 and r["method"] == "stv" and r["elected"] == [1]
    assert counting.count("top_n", [[2]], [1, 2], 1, seed=1)["method"] == "top_n"
