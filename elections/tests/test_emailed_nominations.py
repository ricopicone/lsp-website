"""Nominations that arrive by email, and a call the Board sends itself (task #813).

The 2026 Board sent its own call asking members to email their nominations
to the administrator, so the site must not send a second, contradictory
call, and the administrator must be able to enter what arrives.
"""

import pytest
from django.urls import reverse

from elections import services
from elections.models import Nomination
from elections.tests.factories import (
    make_administrator,
    make_election,
    make_member,
    make_nomination,
)

pytestmark = pytest.mark.django_db


# --- the call ---------------------------------------------------------------------------

def test_call_not_emailed_when_the_setting_is_off(mailoutbox,
                                                 django_capture_on_commit_callbacks):
    make_member()
    e = make_election("nominating", email_call=False)
    with django_capture_on_commit_callbacks(execute=True):
        assert services.advance_elections()["calls"] == 0
    e.refresh_from_db()
    assert e.call_sent_at is not None          # settled, so it isn't retried
    assert "the Board sends its own" in e.audit_notes
    assert mailoutbox == []


def test_call_still_emailed_by_default(mailoutbox, django_capture_on_commit_callbacks):
    make_member()
    make_election("nominating")
    with django_capture_on_commit_callbacks(execute=True):
        assert services.advance_elections()["calls"] == 1
    assert len(mailoutbox) == 1


# --- entering a nomination ---------------------------------------------------------------

@pytest.mark.parametrize("phase", ["nominating", "review"])
def test_administrator_enters_a_nomination(phase):
    e = make_election(phase)
    admin, member = make_administrator(), make_member(role="candidate_scholar")
    n = services.enter_nomination(e, member, "  My letter.  ", admin)
    assert n.letter == "My letter."
    assert n.entered_by == admin
    assert n.status == Nomination.Status.PENDING
    assert n.role_at_submission == "candidate_scholar"
    assert "Entered the nomination of" in e.audit_notes


@pytest.mark.parametrize("phase", ["draft", "slate", "voting"])
def test_entering_refused_outside_nominations_and_review(phase):
    e = make_election(phase)
    with pytest.raises(services.ElectionError):
        services.enter_nomination(e, make_member(), "Letter", make_administrator())


@pytest.mark.parametrize("role", ["pre_candidate", "external"])
def test_entering_refused_for_someone_who_may_not_stand(role):
    e = make_election("nominating")
    with pytest.raises(services.ElectionError, match="may stand"):
        services.enter_nomination(e, make_member(role=role), "Letter",
                                  make_administrator())


def test_entering_refused_once_the_board_has_decided():
    e = make_election("review")
    n = make_nomination(e, status="accepted")
    with pytest.raises(services.ElectionError, match="already decided"):
        services.enter_nomination(e, n.user, "New letter", make_administrator())


def test_entering_replaces_a_pending_letter_and_revives_a_withdrawal():
    e = make_election("nominating")
    n = make_nomination(e, status="pending", letter="Old")
    services.withdraw_nomination(n)
    services.enter_nomination(e, n.user, "New", make_administrator())
    n.refresh_from_db()
    assert n.letter == "New" and n.is_live


def test_nominations_tab_enters_by_email(client, mailoutbox,
                                         django_capture_on_commit_callbacks):
    e = make_election("nominating")
    member = make_member(email="runner@x.test")
    client.force_login(make_administrator())
    url = reverse("elections:admin_enter_nomination", args=[e.slug])
    with django_capture_on_commit_callbacks(execute=True):
        r = client.post(url, {"email": "RUNNER@x.test", "letter": "I would serve."})
    assert r.status_code == 302
    n = Nomination.objects.get(election=e, user=member)
    assert n.letter == "I would serve."
    assert [m.to for m in mailoutbox] == [["runner@x.test"]]   # the usual receipt
    page = client.get(reverse("elections:admin_nominations", args=[e.slug]))
    assert "Entered by" in page.content.decode()


def test_nominations_tab_shows_the_form_only_when_entry_is_open(client):
    client.force_login(make_administrator())
    open_e, done_e = make_election("review"), make_election("voting")
    url = "elections:admin_enter_nomination"
    assert reverse(url, args=[open_e.slug]) in client.get(
        reverse("elections:admin_nominations", args=[open_e.slug])).content.decode()
    assert reverse(url, args=[done_e.slug]) not in client.get(
        reverse("elections:admin_nominations", args=[done_e.slug])).content.decode()


def test_entering_is_the_administrators_alone(client):
    e = make_election("nominating")
    member = make_member()
    client.force_login(make_member())
    r = client.post(reverse("elections:admin_enter_nomination", args=[e.slug]),
                    {"email": member.email, "letter": "x"})
    assert r.status_code == 404
    assert not Nomination.objects.exists()
