"""The Guides section: index, detail pages, and the "Try it now" link."""

from __future__ import annotations

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_guides_index_lists_guides(client):
    r = client.get(reverse("guides_index"))
    assert r.status_code == 200
    body = r.content.decode()
    # Seeded guides appear by title.
    assert "Your profile" in body
    assert "Seminars" in body


@pytest.mark.django_db
def test_guide_detail_renders_markdown(client):
    r = client.get(reverse("guide_detail", args=["profile"]))
    assert r.status_code == 200
    body = r.content.decode()
    assert "Your profile" in body
    # Markdown body rendered to HTML (a heading from profile.md).
    assert "Editing your profile" in body


@pytest.mark.django_db
def test_guide_detail_shows_try_it_link_for_tasked_guide(client):
    # profile.md declares `task: complete_profile`, which resolves to /accounts/profile/.
    r = client.get(reverse("guide_detail", args=["profile"]))
    assert "Try it now" in r.content.decode()
    assert reverse("profile_edit") in r.content.decode()


@pytest.mark.django_db
def test_guide_detail_unknown_slug_404(client):
    assert client.get("/guides/no-such-guide/").status_code == 404
