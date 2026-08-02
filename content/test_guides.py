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
def test_guide_detail_shows_start_walkthrough_when_enabled(client, settings):
    # profile.md declares `checklist: profile`; with walkthroughs enabled the
    # guide offers a "Start this walkthrough" button.
    settings.PREVIEW_TOUR_ENABLED = True
    settings.PREVIEW_TOUR_PUBLIC = True
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.create_user(email="g@example.com", password="x")
    client.force_login(user)
    body = client.get(reverse("guide_detail", args=["profile"])).content.decode()
    assert "Start this walkthrough" in body
    assert reverse("core:set_walkthrough") in body


@pytest.mark.django_db
def test_guide_detail_hides_start_when_walkthroughs_disabled(client, settings):
    settings.PREVIEW_TOUR_ENABLED = False
    body = client.get(reverse("guide_detail", args=["profile"])).content.decode()
    assert "Start this walkthrough" not in body


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


@pytest.mark.django_db
def test_logging_in_guide_public_and_linked(client):
    # Public (no login) — the audience is people who can't sign in yet.
    body = client.get(reverse("guide_detail", args=["logging-in"])).content.decode()
    assert "sign-in link" in body
    assert "/accounts/login/" in body
    assert "/accounts/password/reset/" in body
    # Listed on the index.
    assert "Logging in" in client.get(reverse("guides_index")).content.decode()


@pytest.mark.django_db
def test_faculty_guide_listed_and_answers_the_pricing_code_question(client):
    body = client.get(reverse("guide_detail", args=["faculty"])).content.decode()
    # The question that prompted the guide: a reduced fee for someone outside
    # the school.
    assert "free account" in body
    assert "Fixed amount" in body
    assert "one use" in body
    # Where the tools are, for both kinds of group.
    assert "Roster" in body
    assert "reading group" in body.lower()
    # Listed on the index like every other guide.
    assert "Running a seminar or reading group" in client.get(
        reverse("guides_index"),
    ).content.decode()


@pytest.mark.django_db
def test_faculty_guide_is_public_and_points_at_the_member_guide(client):
    """No login gate (nothing in it is confidential), and it hands anyone who
    wanted the *registering* side over to the member guide."""
    r = client.get(reverse("guide_detail", args=["faculty"]))
    assert r.status_code == 200
    assert reverse("guide_detail", args=["seminars"]) in r.content.decode()
