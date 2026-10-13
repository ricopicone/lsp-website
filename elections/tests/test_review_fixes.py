"""Regressions from the whole-branch review (task #813)."""

from datetime import timedelta

import pytest
from django.db.models import ProtectedError
from django.urls import reverse
from django.utils import timezone

from elections import ballots, counting, services
from elections.models import Election
from elections.tests.factories import (
    make_administrator,
    make_director,
    make_election,
    make_member,
    make_nomination,
)

pytestmark = pytest.mark.django_db
FMT = "%Y-%m-%dT%H:%M"


def _late_review(**kw):
    """The Board is still reviewing after both voting dates have passed."""
    now = timezone.now()
    d = timedelta(days=1)
    return make_election(
        "review", nominations_open_at=now - 4 * d, nominations_close_at=now - 3 * d,
        voting_open_at=now - 2 * d, voting_close_at=now - d, **kw,
    )


def _post_settings(client, e, **changes):
    loc = timezone.localtime
    data = {
        "title": e.title, "seats": e.seats, "count_method": e.count_method,
        "show_during_voting": e.show_during_voting, "show_results": e.show_results,
        "nominations_open_at": loc(e.nominations_open_at).strftime(FMT),
        "nominations_close_at": loc(e.nominations_close_at).strftime(FMT),
        "voting_open_at": loc(e.voting_open_at).strftime(FMT),
        "voting_close_at": loc(e.voting_close_at).strftime(FMT),
        "results_due": "",
    }
    data.update(changes)
    return client.post(reverse("elections:admin_settings", args=[e.slug]), data)


# --- 1: a late Board review must not strand the election -----------------------------

def test_voting_dates_movable_until_the_slate_is_published(client):
    e = _late_review()
    make_nomination(e)
    client.force_login(make_administrator())
    later = timezone.now()
    r = _post_settings(client, e,
                       voting_open_at=(later + timedelta(days=1)).strftime(FMT),
                       voting_close_at=(later + timedelta(days=5)).strftime(FMT))
    assert r.status_code == 302
    e.refresh_from_db()
    assert e.voting_close_at > timezone.now()
    services.publish_slate(e, make_member())  # no longer stuck


def test_close_voting_now_refused_before_voting_opens():
    e = make_election("review", voting_open_at=timezone.now() - timedelta(hours=1))
    with pytest.raises(services.ElectionError):
        services.close_now(e, "voting", make_member())


# --- 2: an uncontested slate must not open a vote --------------------------------------

def test_uncontested_late_slate_refuses_to_open_voting():
    now = timezone.now()
    e = make_election("review", seats=2, voting_open_at=now - timedelta(hours=1),
                      voting_close_at=now + timedelta(days=3))
    make_nomination(e)
    make_nomination(e)
    with pytest.raises(services.ElectionError, match="without a vote"):
        services.publish_slate(e, make_member())


def test_acclaim_from_review_publishes_and_closes():
    now = timezone.now()
    e = make_election("review", seats=2, voting_open_at=now - timedelta(hours=1),
                      voting_close_at=now + timedelta(days=3))
    make_nomination(e)
    make_nomination(e, status="declined")
    services.acclaim(e, make_member())
    e.refresh_from_db()
    assert e.phase == Election.Phase.ACCLAIMED and e.slate_published_at


def test_acclaim_from_review_waits_for_every_decision():
    e = make_election("review", seats=2)
    make_nomination(e, status="pending")
    with pytest.raises(services.ElectionError):
        services.acclaim(e, make_member())


# --- 3: no ballots, nobody elected -------------------------------------------------------

def test_zero_ballot_count_elects_nobody():
    for method in ("stv", "top_n"):
        r = counting.count(method, [], [1, 2, 3], 2, seed=1)
        assert r["elected"] == [] and r["lots"] == []


# --- 5: one-shot actions can't run twice from stale pages ----------------------------------

def test_count_cannot_be_rerun_from_a_stale_page():
    e = make_election("closed", seats=1)
    a = make_nomination(e)
    services.ensure_roll_frozen(e)
    ballots.cast(e, make_member(), [a.id])
    first, stale = Election.objects.get(pk=e.pk), Election.objects.get(pk=e.pk)
    services.run_count(first, make_member())
    with pytest.raises(services.ElectionError):
        services.run_count(stale, make_member())


def test_slate_cannot_be_published_twice_from_stale_pages():
    e = make_election("review")
    make_nomination(e)
    first, stale = Election.objects.get(pk=e.pk), Election.objects.get(pk=e.pk)
    services.publish_slate(first, make_member())
    with pytest.raises(services.ElectionError):
        services.publish_slate(stale, make_member())


# --- 6: a ranked candidate can't be deleted out from under the ballots --------------------

def test_deleting_a_ranked_nomination_is_refused():
    e = make_election("voting")
    a = make_nomination(e)
    ballots.cast(e, make_member(), [a.id])
    with pytest.raises(ProtectedError):
        a.delete()


# --- 9: a new draft doesn't hide the election in progress -----------------------------------

def test_draft_does_not_displace_a_live_election():
    live = make_election("voting")
    make_election("draft", nominations_open_at=timezone.now() + timedelta(days=300),
                  nominations_close_at=timezone.now() + timedelta(days=301),
                  voting_open_at=timezone.now() + timedelta(days=302),
                  voting_close_at=timezone.now() + timedelta(days=303))
    assert services.current_election() == live


# --- 11: no self-review, no deciding a withdrawn nomination ---------------------------------

def test_director_cannot_decide_their_own_nomination(client):
    e = make_election("review")
    director = make_director()
    n = make_nomination(e, user=director, status="pending")
    with pytest.raises(services.ElectionError):
        services.review_nomination(n, director, "accepted")
    client.force_login(director)
    page = client.get(reverse("elections:board_review")).content.decode()
    assert "your own nomination" in page


def test_withdrawn_nomination_cannot_be_decided():
    e = make_election("review")
    n = make_nomination(e, status="pending")
    n.withdrawn_at = timezone.now()
    n.save()
    with pytest.raises(services.ElectionError):
        services.review_nomination(n, make_member(), "accepted")
