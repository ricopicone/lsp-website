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


@pytest.mark.django_db
def test_all_listed_guides_render(client):
    """Every guide in GUIDE_SLUGS that has a file renders without error."""
    from content import guides
    rendered = guides.all_guides()
    assert len(rendered) >= 6  # profile, seminars, parletre, cartels, my-formation, tuition-dues
    for g in rendered:
        r = client.get(reverse("guide_detail", args=[g.slug]))
        assert r.status_code == 200, g.slug


@pytest.mark.django_db
def test_staff_guides_hidden_from_non_staff(client):
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.create_user(email="plain@example.com", password="x")
    client.force_login(user)
    assert "Your staff guides" not in client.get(reverse("guides_index")).content.decode()


@pytest.mark.django_db
def test_staff_guides_shown_to_staff(client):
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.create_user(
        email="staff@example.com", password="x", is_staff=True, is_superuser=True,
    )
    client.force_login(user)
    body = client.get(reverse("guides_index")).content.decode()
    assert "Your staff guides" in body
    assert reverse("treasurer_help") in body
