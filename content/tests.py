"""Tests for the content app — the /about/ page with inline committee rosters."""

from __future__ import annotations

from datetime import date

import pytest

from accounts.models import User
from committees.models import Committee


@pytest.mark.django_db
def test_about_page_renders_with_committee_roster(client):
    """Regression: the roster prefetch must traverse the committee's workgroup
    (the old CommitteeMembership reverse was removed in the Stage-4 fold-in)."""
    board = Committee.objects.get(slug="board")
    board.public = True
    board.save(update_fields=["public"])
    member = User.objects.create_user(
        email="boardie@example.com", first_name="Bea", last_name="Member"
    )
    board.add_member(member, start_date=date(2026, 1, 1))

    resp = client.get("/about/")
    assert resp.status_code == 200
    assert b"Bea" in resp.content
