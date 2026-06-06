"""Gating + summon lifecycle for the walkthrough context processor."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from core.context_processors import preview_tour


def _req(rf, user, cookie=None):
    request = rf.get("/")
    request.user = user
    if cookie:
        request.COOKIES["lsp_walkthrough"] = cookie
    return request


@pytest.mark.django_db
def test_disabled_hides_for_everyone(rf, settings):
    settings.PREVIEW_TOUR_ENABLED = False
    u = get_user_model().objects.create_user(email="a@example.com", password="x")
    ctx = preview_tour(_req(rf, u, cookie="profile"))
    assert ctx["walkthroughs_enabled"] is False
    assert ctx["show_preview_tour"] is False


@pytest.mark.django_db
def test_allowlist_gates_who_can_use_walkthroughs(rf, settings):
    settings.PREVIEW_TOUR_ENABLED = True
    settings.PREVIEW_TOUR_PUBLIC = False
    settings.PREVIEW_TOUR_ALLOWLIST = ["allowed@example.com"]
    U = get_user_model()
    allowed = U.objects.create_user(email="allowed@example.com", password="x")
    other = U.objects.create_user(email="other@example.com", password="x")
    assert preview_tour(_req(rf, other))["walkthroughs_enabled"] is False
    assert preview_tour(_req(rf, allowed))["walkthroughs_enabled"] is True


@pytest.mark.django_db
def test_public_enables_walkthroughs_for_everyone(rf, settings):
    settings.PREVIEW_TOUR_ENABLED = True
    settings.PREVIEW_TOUR_PUBLIC = True
    settings.PREVIEW_TOUR_ALLOWLIST = ["someone-else@example.com"]
    u = get_user_model().objects.create_user(email="random@example.com", password="x")
    assert preview_tour(_req(rf, u))["walkthroughs_enabled"] is True


@pytest.mark.django_db
def test_card_hidden_until_a_walkthrough_is_active(rf, settings):
    """Enabled but no active walkthrough → no card (summon-based, not always-on)."""
    settings.PREVIEW_TOUR_ENABLED = True
    settings.PREVIEW_TOUR_PUBLIC = True
    u = get_user_model().objects.create_user(email="b@example.com", password="x")
    ctx = preview_tour(_req(rf, u))  # no cookie
    assert ctx["walkthroughs_enabled"] is True
    assert ctx["show_preview_tour"] is False


@pytest.mark.django_db
def test_active_walkthrough_shows_its_card(rf, settings):
    settings.PREVIEW_TOUR_ENABLED = True
    settings.PREVIEW_TOUR_PUBLIC = True
    u = get_user_model().objects.create_user(email="c@example.com", password="x")
    ctx = preview_tour(_req(rf, u, cookie="profile"))
    assert ctx["show_preview_tour"] is True
    assert ctx["walkthrough_id"] == "profile"
    assert ctx["walkthrough_title"] == "Set up your profile"
    assert [t["id"] for t in ctx["preview_tour_tasks"]][0] == "pf_photo"


@pytest.mark.django_db
def test_unknown_walkthrough_cookie_shows_nothing(rf, settings):
    settings.PREVIEW_TOUR_ENABLED = True
    settings.PREVIEW_TOUR_PUBLIC = True
    u = get_user_model().objects.create_user(email="d@example.com", password="x")
    ctx = preview_tour(_req(rf, u, cookie="bogus"))
    assert ctx["show_preview_tour"] is False
