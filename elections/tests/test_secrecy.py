"""Ballot secrecy holds by structure (task #813): the voter-to-vote link is
shown to nobody but the voter."""

import pathlib
import subprocess

from django.contrib import admin

from elections.models import Ballot, BallotRanking

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _tracked(pattern, *globs):
    # git grep over tracked files only, so sibling worktrees aren't swept.
    out = subprocess.run(["git", "grep", "-l", pattern, "--", *globs],
                         cwd=ROOT, capture_output=True, text=True).stdout
    return out.split()


def test_ballots_not_in_django_admin():
    assert Ballot not in admin.site._registry
    assert BallotRanking not in admin.site._registry


def test_devapi_exposes_no_elections():
    from devapi import urls
    patterns = [str(p.pattern).lower() for p in urls.urlpatterns]
    assert not any("election" in p or "ballot" in p for p in patterns)


def test_only_ballots_module_reads_rankings():
    allowed = {"elections/models.py", "elections/ballots.py"}
    offenders = [p for p in _tracked("BallotRanking", "*.py")
                 if p not in allowed and "/migrations/" not in p and "/tests/" not in p]
    assert offenders == []


def test_no_template_shows_when_a_ballot_was_cast():
    # In an electorate of about sixty, the time a ballot was cast can
    # identify the voter.
    assert _tracked("cast_at", "*.html", "*.txt") == []
