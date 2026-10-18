"""The member's My LSP → Election tab (task #813)."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from elections import ballots, services
from elections.tests.factories import (
    make_administrator,
    make_election,
    make_member,
    make_nomination,
)

pytestmark = pytest.mark.django_db


def tab():
    return reverse("formation:formation") + "?tab=election"


def _page(client, user):
    client.force_login(user)
    return client.get(tab()).content.decode()


def test_no_tab_without_an_election(client):
    assert "?tab=election" not in _page(client, make_member())


def test_no_tab_in_draft(client):
    make_election("draft")
    assert "?tab=election" not in _page(client, make_member())


def test_no_tab_for_non_voters(client):
    make_election("nominating")
    assert "?tab=election" not in _page(client, make_member(role="external"))


def test_tab_for_voters(client):
    make_election("nominating")
    assert "?tab=election" in _page(client, make_member(role="pre_candidate"))


def test_tab_gone_30_days_after_results(client):
    e = make_election("closed", results_published_at=timezone.now() - timedelta(days=31),
                      counted_at=timezone.now() - timedelta(days=32))
    assert "?tab=election" not in _page(client, make_member())
    e.results_published_at = timezone.now() - timedelta(days=2)
    e.save()
    assert "?tab=election" in _page(client, make_member())


def test_nominate_flow(client):
    e = make_election("nominating")
    u = make_member(role="candidate")
    assert "Motivation letter" in _page(client, u)
    client.post(reverse("elections:nominate", args=[e.slug]), {"letter": "I will serve."})
    assert e.nominations.get().letter == "I will serve."
    page = client.get(tab()).content.decode()
    assert "I will serve." in page and "Withdraw" in page


def test_withdraw(client):
    e = make_election("nominating")
    u = make_member(role="candidate")
    n = make_nomination(e, user=u, status="pending")
    client.force_login(u)
    client.post(reverse("elections:withdraw", args=[e.slug]))
    n.refresh_from_db()
    assert n.withdrawn_at


def test_pre_candidate_sees_no_form(client):
    make_election("nominating")
    page = _page(client, make_member(role="pre_candidate"))
    assert "Motivation letter" not in page


def test_administrator_sees_no_form(client):
    make_election("nominating")
    assert "Motivation letter" not in _page(client, make_administrator())


def test_nominee_sees_status_in_review(client):
    e = make_election("review")
    u = make_member()
    make_nomination(e, user=u, status="declined")
    page = _page(client, u)
    assert "under review" in page.lower()
    assert "Not accepted" not in page  # the decision waits for the slate


def test_nominee_sees_decision_after_slate(client):
    e = make_election("slate")
    u = make_member()
    make_nomination(e, user=u, status="declined")
    assert "not accepted" in _page(client, u).lower()


def test_slate_shows_letters(client):
    e = make_election("slate")
    make_nomination(e, letter="Read my letter")
    assert "Read my letter" in _page(client, make_member())


def test_ballot_view_freezes_roll_lazily(client):
    e = make_election("voting")
    a = make_nomination(e)
    page = _page(client, make_member())
    e.refresh_from_db()
    assert e.roll_frozen_at and f"rank_{a.id}" in page


def test_cast_once_and_no_second_ballot(client):
    e = make_election("voting")
    a, b = make_nomination(e), make_nomination(e)
    v = make_member()
    client.force_login(v)
    client.post(reverse("elections:ballot", args=[e.slug]),
                {f"rank_{a.id}": "1", f"rank_{b.id}": "2"})
    r = client.post(reverse("elections:ballot", args=[e.slug]),
                    {f"rank_{b.id}": "1"}, follow=True)
    assert b"already voted" in r.content
    assert ballots.anonymous_ballots(e) == [[a.id, b.id]]


def test_duplicate_rank_rejected(client):
    e = make_election("voting")
    a, b = make_nomination(e), make_nomination(e)
    v = make_member()
    client.force_login(v)
    r = client.post(reverse("elections:ballot", args=[e.slug]),
                    {f"rank_{a.id}": "1", f"rank_{b.id}": "1"}, follow=True)
    assert not ballots.has_voted(v, e) and b"different rank" in r.content


def test_off_roll_member_gets_no_ballot(client):
    from elections.models import VoterRollEntry
    e = make_election("voting")
    make_nomination(e)
    u = make_member()
    VoterRollEntry.objects.create(election=e, user=u, override="remove", reason="unpaid")
    page = _page(client, u)
    assert "rank_" not in page and "not on this election's voter roll" in page


def test_turnout_only_when_enabled(client):
    e = make_election("voting", show_during_voting="turnout")
    make_nomination(e)
    v = make_member()
    assert "Turnout" in _page(client, v)
    e.show_during_voting = "status"
    e.save()
    assert "Turnout" not in client.get(tab()).content.decode()


def test_results_winners_only_vs_full(client):
    e = make_election("closed", seats=1)
    a = make_nomination(e, user=make_member(first="Ada", last="Winningham"))
    v = make_member()
    services.ensure_roll_frozen(e)
    ballots.cast(e, v, [a.id])
    admin = make_administrator()
    services.run_count(e, admin)
    services.publish_results(e, admin)
    page = _page(client, v)
    assert "Winningham" in page and "Stage" not in page
    e.show_results = "full"
    e.save()
    assert "Stage" in client.get(tab()).content.decode()


def test_no_tally_while_counted_but_unpublished(client):
    e = make_election("closed", seats=1)
    a = make_nomination(e, user=make_member(last="Hiddenresult"))
    v = make_member()
    services.ensure_roll_frozen(e)
    ballots.cast(e, v, [a.id])
    services.run_count(e, make_administrator())
    page = _page(client, v)
    assert "Elected" not in page
