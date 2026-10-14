"""The minors deferred from the whole-branch review (task #813)."""

import subprocess

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from elections import queries, services
from elections.models import Election, VoterRollEntry
from elections.tests.factories import (
    make_administrator,
    make_election,
    make_member,
    make_nomination,
)
from elections.tests.test_secrecy import ROOT

pytestmark = pytest.mark.django_db


# --- 4: an override made from a page loaded before the freeze still lands on the roll --

def test_override_from_a_stale_page_lands_on_the_frozen_roll():
    e = make_election("voting")
    stale = Election.objects.get(pk=e.pk)        # loaded before the freeze
    services.ensure_roll_frozen(e)
    outsider = make_member(role="external")
    services.set_override(stale, outsider, VoterRollEntry.Override.ADD, "Paid late",
                          make_administrator())
    row = VoterRollEntry.objects.get(election=e, user=outsider)
    assert row.on_roll


# --- 7: the secrecy scan covers the related name too ------------------------------------

def test_only_ballots_module_follows_the_rankings_relation():
    out = subprocess.run(
        ["git", "grep", "-lE", r"\.rankings\b|rankings__", "--", "*.py", "*.html"],
        cwd=ROOT, capture_output=True, text=True).stdout.split()
    offenders = [p for p in out
                 if p != "elections/ballots.py" and "/tests/" not in p]
    assert offenders == []


# --- 8: the tab check costs nothing the second time in a request ------------------------

def test_visible_election_is_computed_once_per_user_object(django_assert_num_queries):
    make_election("voting")
    user = get_user_model().objects.select_related("profile").get(pk=make_member().pk)
    assert queries.visible_election_for(user) is not None
    with django_assert_num_queries(0):
        assert queries.visible_election_for(user) is not None


# --- 10: a ballot refused for an error keeps the voter's selections ---------------------

def test_invalid_ballot_keeps_the_selections(client):
    e = make_election("voting")
    a, b = make_nomination(e), make_nomination(e)
    voter = make_member()
    client.force_login(voter)
    client.post(reverse("elections:ballot", args=[e.slug]),
                {f"rank_{a.id}": "1", f"rank_{b.id}": "1"})
    page = client.get(reverse("formation:formation") + "?tab=election&change=1")
    html = page.content.decode()
    assert html.count('<option value="1" selected>') == 2
    # Shown once, then forgotten.
    again = client.get(reverse("formation:formation") + "?tab=election&change=1")
    assert '<option value="1" selected>' not in again.content.decode()


# --- 12: a call for nominations is never sent after nominations have closed ------------

def test_no_late_call_once_nominations_have_closed(mailoutbox,
                                                   django_capture_on_commit_callbacks):
    make_member()
    e = make_election("review")
    with django_capture_on_commit_callbacks(execute=True):
        assert services.advance_elections()["calls"] == 0
    e.refresh_from_db()
    assert e.call_sent_at is not None          # settled, so it isn't retried
    assert "not sent" in e.audit_notes
    assert mailoutbox == []
    assert e.phase == "review"
