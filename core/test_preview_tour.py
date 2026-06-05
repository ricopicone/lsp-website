"""Gating for the limited-preview onboarding tour context processor."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from core.context_processors import preview_tour


def _req(rf, user):
    request = rf.get("/")
    request.user = user
    return request


@pytest.mark.django_db
def test_disabled_hides_for_everyone(rf, settings):
    settings.PREVIEW_TOUR_ENABLED = False
    u = get_user_model().objects.create_user(email="a@example.com", password="x")
    assert preview_tour(_req(rf, u))["show_preview_tour"] is False


@pytest.mark.django_db
def test_allowlist_gates_when_not_public(rf, settings):
    settings.PREVIEW_TOUR_ENABLED = True
    settings.PREVIEW_TOUR_PUBLIC = False
    settings.PREVIEW_TOUR_ALLOWLIST = ["allowed@example.com"]
    U = get_user_model()
    allowed = U.objects.create_user(email="allowed@example.com", password="x")
    other = U.objects.create_user(email="other@example.com", password="x")
    assert preview_tour(_req(rf, other))["show_preview_tour"] is False
    assert preview_tour(_req(rf, allowed))["show_preview_tour"] is True


@pytest.mark.django_db
def test_public_shows_for_everyone(rf, settings):
    settings.PREVIEW_TOUR_ENABLED = True
    settings.PREVIEW_TOUR_PUBLIC = True
    settings.PREVIEW_TOUR_ALLOWLIST = ["someone-else@example.com"]
    u = get_user_model().objects.create_user(email="random@example.com", password="x")
    assert preview_tour(_req(rf, u))["show_preview_tour"] is True


@pytest.mark.django_db
def test_empty_allowlist_means_everyone(rf, settings):
    settings.PREVIEW_TOUR_ENABLED = True
    settings.PREVIEW_TOUR_PUBLIC = False
    settings.PREVIEW_TOUR_ALLOWLIST = [""]  # how `DJANGO_..._ALLOWLIST=` parses
    u = get_user_model().objects.create_user(email="anyone@example.com", password="x")
    assert preview_tour(_req(rf, u))["show_preview_tour"] is True
