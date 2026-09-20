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


@pytest.mark.django_db
def test_starting_a_walkthrough_signals_a_fresh_start(client):
    from django.urls import reverse
    resp = client.get(
        reverse("core:set_walkthrough") + "?id=applications_coordinator&next=/"
    )
    assert resp.status_code == 302
    # Sets the active-walkthrough cookie + a one-shot "fresh" signal the card
    # uses to clear remembered ticks (so re-clicking restarts).
    assert resp.cookies["lsp_walkthrough"].value == "applications_coordinator"
    assert resp.cookies["lsp_wt_fresh"].value == "applications_coordinator"


@pytest.mark.django_db
def test_card_marks_visit_ticking_steps_and_scrolls_its_list(client, settings):
    """The card's list scrolls on its own (it cut off mid-list on the faculty
    walkthrough) and a step that ticks on visit says so in the markup, so the
    script can tick it when the member lands on its page."""
    settings.PREVIEW_TOUR_ENABLED = True
    settings.PREVIEW_TOUR_PUBLIC = True
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(email="fac@example.com", password="x")
    client.force_login(user)
    client.cookies["lsp_walkthrough"] = "faculty"
    body = client.get("/guides/faculty/").content.decode()
    assert 'data-wt-task="fac_workspace" data-wt-manual="1" data-wt-visit="1"' in body
    assert 'data-wt-task="fac_status" data-wt-manual="1"' in body
    assert 'data-wt-task="fac_status" data-wt-manual="1" data-wt-visit' not in body
    assert 'id="lsp-tour-list"' in body
    assert "overflow-y: auto" in body
    # A manual tick that is done must win on background too, or the check
    # renders primary-content on transparent (invisible).
    assert "#lsp-preview-tour button.lsp-tour-tick--done" in body


@pytest.mark.django_db
def test_card_renders_a_hidden_hop_per_step_that_has_one(client, settings):
    """One hidden popover per step with a hop on this page; the card script
    activates the first unfinished one (route-hints spec)."""
    settings.PREVIEW_TOUR_ENABLED = True
    settings.PREVIEW_TOUR_PUBLIC = True
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(email="hop@example.com", password="x")
    client.force_login(user)
    client.cookies["lsp_walkthrough"] = "faculty"
    body = client.get("/guides/faculty/").content.decode()
    # Off the route, every faculty step's hop is the avatar fallback.
    assert 'data-wt-hop="fac_workspace"' in body
    assert 'data-wt-hop="fac_room"' in body
    assert 'data-hop-selector="[data-tour=avatar]"' in body
    assert 'id="lsp-hop-fac_workspace"' in body
    assert "Open your menu" in body
    # The card script wires the hop through the shared hint helper, session-scoped.
    assert "lsp-wt-hop:" in body
    assert "session: true" in body
