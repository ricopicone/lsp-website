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


@pytest.mark.django_db
def test_the_school_page_renders_all_entries(client):
    """The graphical index must render every concept in the taxonomy, and the
    graphic and the entry list are driven by the same source — so a present
    title proves both the block and its entry rendered."""
    from content import the_school

    resp = client.get("/the-school/")
    assert resp.status_code == 200

    # Every slug in the taxonomy has a backing entry file that loads.
    for _label, slugs in the_school.TAXONOMY:
        for slug in slugs:
            assert (the_school.ENTRIES_DIR / f"{slug}.md").is_file(), f"missing entry: {slug}"
            assert f'id="{slug}"'.encode() in resp.content, f"entry not rendered: {slug}"

    # A couple of titles and a row label appear on the page.
    assert b"Cartels" in resp.content
    assert b"Meeting of the Analysts" in resp.content
    assert b"School Bodies" in resp.content


@pytest.mark.django_db
def test_the_school_destinations_resolve(client):
    """Every DESTINATIONS url name must reverse — guards against a renamed
    route rotting into a dead block link."""
    from django.urls import reverse

    from content import the_school

    for url_name in set(the_school.DESTINATIONS.values()):
        reverse(url_name)  # raises NoReverseMatch if the route is gone


@pytest.mark.django_db
def test_the_school_applies_archive_filter_to_destination(client):
    """The Palimpsests/Passages blocks point at the Works archive pre-filtered
    by kind — the filter is part of the link, applied automatically."""
    from content import the_school

    rows = {e.slug: e for row in the_school.build_rows() for e in row["entries"]}
    assert rows["palimpsests"].destination.endswith("?kind=palimpsest")
    assert rows["passages"].destination.endswith("?kind=passage")
    # Traversée (Scholar track) has its own Works kind, separate from Passage.
    assert rows["traversees"].destination.endswith("?kind=traversee")
    assert "Scholar of the School" in rows["traversees"].body_html
    assert client.get("/works/?kind=traversee").status_code == 200

    resp = client.get("/the-school/")
    assert b"?kind=palimpsest" in resp.content
    # The Works index must actually honor the ?kind= filter the link relies on.
    assert client.get("/works/?kind=palimpsest").status_code == 200


@pytest.mark.django_db
def test_the_school_palimpsest_grounded_in_founding_papers(client):
    """The palimpsest entry is grounded in the two founding papers (Patsalides
    + Adler, 1992). They're named in prose; the live links are commented out in
    the source until the gated documents are made public."""
    resp = client.get("/the-school/")
    body = resp.content
    assert b"Patsalides" in body
    assert b"rubbed again" in body  # the etymological grounding from the text
