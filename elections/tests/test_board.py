"""The Board reviews nominations (task #813; bylaws Art. 3 §1)."""

import pytest
from django.urls import reverse

from elections import services
from elections.tests.factories import (
    make_director, make_election, make_member, make_nomination,
)

pytestmark = pytest.mark.django_db


def test_anonymous_to_login(client):
    r = client.get(reverse("elections:board_review"))
    assert r.status_code == 302 and "login" in r.url


def test_non_director_404(client):
    client.force_login(make_member())
    assert client.get(reverse("elections:board_review")).status_code == 404


def test_director_sees_letters_and_the_personal_contact_rule(client):
    e = make_election("review")
    make_nomination(e, status="pending", letter="My letter here")
    client.force_login(make_director())
    page = client.get(reverse("elections:board_review")).content.decode()
    assert "My letter here" in page and "contacted personally" in page


def test_decide(client):
    e = make_election("review")
    n = make_nomination(e, status="pending")
    director = make_director()
    client.force_login(director)
    client.post(reverse("elections:board_decide", args=[n.pk]),
                {"status": "declined", "note": "not yet eligible"})
    n.refresh_from_db()
    assert n.status == "declined" and n.reviewed_by == director
    assert n.board_note == "not yet eligible"


def test_decide_refused_outside_review(client):
    e = make_election("slate")
    n = make_nomination(e)
    client.force_login(make_director())
    r = client.post(reverse("elections:board_decide", args=[n.pk]),
                    {"status": "declined"}, follow=True)
    n.refresh_from_db()
    assert n.status == "accepted" and b"after they close" in r.content


def test_withdrawn_nominations_not_listed_for_decision(client):
    from django.utils import timezone
    e = make_election("review")
    make_nomination(e, status="pending", letter="Gone now", ).__class__.objects.update(
        withdrawn_at=timezone.now())
    client.force_login(make_director())
    assert "Gone now" not in client.get(reverse("elections:board_review")).content.decode()


def test_board_page_never_shows_the_roll(client):
    e = make_election("voting")
    cand = make_nomination(e)
    services.cast_ballot(e, make_member(last="Ballotcaster"), [cand.id])
    client.force_login(make_director())
    page = client.get(reverse("elections:board_review")).content.decode()
    assert "Ballotcaster" not in page and "Voted" not in page


def test_board_landing_shows_card_during_review(client):
    e = make_election("review")
    make_nomination(e, status="pending")
    client.force_login(make_director())
    page = client.get(reverse("board_admin")).content.decode()
    assert reverse("elections:board_review") in page
