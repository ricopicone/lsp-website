"""The data-driven walkthrough registry (core.checklists)."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from core.checklists import CHECKLISTS, get_checklist


def test_registry_has_a_walkthrough_per_guide():
    assert set(CHECKLISTS) == {
        "profile", "seminars", "parletre", "cartels", "my_formation", "tuition_dues",
    }
    # No always-on default walkthrough.
    assert "getting_started" not in CHECKLISTS


def test_get_checklist_returns_titled_tasks():
    profile = get_checklist("profile")
    assert profile.title == "Set up your profile"
    assert [t.id for t in profile.tasks][:2] == ["pf_photo", "pf_bio"]
    assert get_checklist("nope") is None


def test_manual_and_auto_task_mix():
    tasks = {t.id: t for t in get_checklist("profile").tasks}
    assert tasks["pf_photo"].manual is False   # auto: ticks from real data
    assert tasks["pf_visibility"].manual is True  # member checks it off


@pytest.mark.django_db
def test_auto_task_resolves_done_from_data(rf):
    user = get_user_model().objects.create_user(email="t@example.com", password="x")
    request = rf.get("/")
    request.user = user
    photo = next(t for t in get_checklist("profile").tasks if t.id == "pf_photo")
    d = photo.resolved(user, request)
    assert d["done"] is False           # no headshot yet
    assert d["url"]                     # profile_edit reverses
    assert d["show_hint"] is True       # not done + has anchor


@pytest.mark.django_db
def test_manual_task_never_done_serverside(rf):
    user = get_user_model().objects.create_user(email="m@example.com", password="x")
    request = rf.get("/")
    request.user = user
    vis = next(t for t in get_checklist("profile").tasks if t.id == "pf_visibility")
    d = vis.resolved(user, request)
    assert d["manual"] is True
    assert d["done"] is False
    assert d["show_hint"] is False      # manual steps never pulse
