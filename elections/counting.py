"""Pure vote counting (task #813): anonymous ranked ballots in, a JSON-ready
result out. No database.

STV follows the counting rules of the Scottish Local Government Elections
Order 2007: Droop quota, weighted inclusive Gregory transfers (every ballot
of an elected candidate moves at its current value x surplus / total),
transfer values truncated to five decimal places, ties broken by the most
recent preceding stage at which the tied candidates differed, then by lot.
Lots are drawn from a seeded generator and recorded, so a count can be
reproduced and a human can redo a draw publicly.

"Most votes" (``top_n``) gives one vote to each of a ballot's top N ranked
candidates, N being the number of seats; the N highest totals win.

Ballots are lists of candidate ids in preference order. Candidate ids in a
ballot that aren't standing are ignored; a ballot naming nobody standing is
not valid.
"""

from __future__ import annotations

import random
from decimal import ROUND_DOWN, Decimal

FIVE_PLACES = Decimal("0.00001")


def _trunc(x: Decimal) -> Decimal:
    return x.quantize(FIVE_PLACES, rounding=ROUND_DOWN)


def _fmt(x: Decimal) -> str:
    return format(x.normalize(), "f")


def _break_tie(tied, history, *, lowest: bool, rng, lots, stage_n):
    """Narrow ``tied`` by the preceding stages, most recent first, then by lot."""
    tied = sorted(tied)
    for totals in reversed(history[:-1]):
        vals = {c: totals.get(c, Decimal(0)) for c in tied}
        target = min(vals.values()) if lowest else max(vals.values())
        tied = [c for c in tied if vals[c] == target]
        if len(tied) == 1:
            return tied[0]
    chosen = rng.choice(tied)
    lots.append({"stage": stage_n, "tied": tied, "chosen": chosen})
    return chosen


def count_stv(ballots, candidates, seats, rng) -> dict:
    cands = list(dict.fromkeys(candidates))
    continuing = set(cands)
    # A paper is [preferences, current position, current value].
    papers = []
    for b in ballots:
        prefs = [c for c in dict.fromkeys(b) if c in continuing]
        if prefs:
            papers.append([prefs, 0, Decimal(1)])
    valid = len(papers)
    quota = Decimal(valid // (seats + 1) + 1)
    piles = {c: [] for c in cands}
    for p in papers:
        piles[p[0][0]].append(p)

    elected, excluded, pending = [], [], []
    stages, lots, history = [], [], []
    held = {}
    exhausted = Decimal(0)

    def totals():
        t = {c: sum((p[2] for p in piles[c]), Decimal(0)) for c in continuing}
        t.update({c: held[c] for c in elected})
        return t

    def record(action, subject):
        t = totals()
        history.append(t)
        stages.append({
            "n": len(stages) + 1,
            "action": action,
            "subject": subject,
            "totals": {str(c): _fmt(t.get(c, Decimal(0)))
                       for c in cands if c not in excluded},
            "exhausted": _fmt(exhausted),
        })
        return t

    def move(paper_list, value_of):
        nonlocal exhausted
        for p in paper_list:
            p[2] = value_of(p[2])
            nxt = next((i for i in range(p[1] + 1, len(p[0]))
                        if p[0][i] in continuing), None)
            if nxt is None:
                exhausted += p[2]
            else:
                p[1] = nxt
                piles[p[0][nxt]].append(p)

    t = record("first", None)
    while True:
        reached = [c for c in continuing if t[c] >= quota]
        while reached:
            top = max(t[c] for c in reached)
            group = [c for c in reached if t[c] == top]
            c = group[0] if len(group) == 1 else _break_tie(
                group, history, lowest=False, rng=rng, lots=lots, stage_n=len(stages))
            continuing.discard(c)
            elected.append(c)
            held[c] = t[c]
            pending.append(c)
            reached.remove(c)
        if len(elected) >= seats:
            break
        if len(continuing) <= seats - len(elected):
            for c in sorted(continuing, key=lambda c: (-t[c], c)):
                elected.append(c)
                held[c] = t[c]
            continuing.clear()
            record("elect_remaining", None)
            break

        surpluses = {c: held[c] - quota for c in pending if held[c] > quota}
        if surpluses:
            big = max(surpluses.values())
            group = [c for c in pending if surpluses.get(c) == big]
            c = group[0] if len(group) == 1 else _break_tie(
                group, history, lowest=False, rng=rng, lots=lots, stage_n=len(stages))
            pending.remove(c)
            surplus, total = surpluses[c], held[c]
            transfer, piles[c] = piles[c], []
            held[c] = quota
            move(transfer, lambda v, s=surplus, tot=total: _trunc(v * s / tot))
            t = record("surplus", c)
            continue

        pending.clear()
        low = min(t[c] for c in continuing)
        group = [c for c in continuing if t[c] == low]
        c = group[0] if len(group) == 1 else _break_tie(
            group, history, lowest=True, rng=rng, lots=lots, stage_n=len(stages))
        continuing.discard(c)
        excluded.append(c)
        transfer, piles[c] = piles[c], []
        move(transfer, lambda v: v)
        t = record("exclude", c)

    return {
        "method": "stv",
        "seats": seats,
        "valid_ballots": valid,
        "quota": _fmt(quota),
        "stages": stages,
        "elected": elected[:seats],
        "excluded": excluded,
        "lots": lots,
    }


def count_top_n(ballots, candidates, seats, rng) -> dict:
    cands = list(dict.fromkeys(candidates))
    standing = set(cands)
    tally = {c: 0 for c in cands}
    valid = 0
    for b in ballots:
        prefs = [c for c in dict.fromkeys(b) if c in standing][:seats]
        if prefs:
            valid += 1
            for c in prefs:
                tally[c] += 1
    order = sorted(cands, key=lambda c: (-tally[c], c))
    elected, lots = [], []
    i = 0
    while len(elected) < seats and i < len(order):
        group = [c for c in order[i:] if tally[c] == tally[order[i]]]
        room = seats - len(elected)
        if len(group) <= room:
            elected.extend(group)
        else:
            chosen = rng.sample(sorted(group), room)
            lots.append({"stage": 1, "tied": sorted(group), "chosen": chosen})
            elected.extend(chosen)
        i += len(group)
    return {
        "method": "top_n",
        "seats": seats,
        "valid_ballots": valid,
        "stages": [{
            "n": 1, "action": "tally", "subject": None,
            "totals": {str(c): str(tally[c]) for c in cands}, "exhausted": "0",
        }],
        "elected": elected,
        "excluded": [],
        "lots": lots,
    }


def count(method: str, ballots, candidates, seats: int, seed: int) -> dict:
    """Run ``method`` ("stv" or "top_n") with a lot generator seeded by ``seed``."""
    rng = random.Random(seed)
    fn = count_stv if method == "stv" else count_top_n
    result = fn(ballots, candidates, seats, rng)
    result["seed"] = seed
    return result
