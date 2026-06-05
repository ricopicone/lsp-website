"""The data-driven checklist engine (core.checklists)."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from core.checklists import PREVIEW_CHECKLIST_ID, find_task, get_checklist


def test_preview_checklist_task_order():
    assert [t.id for t in get_checklist(PREVIEW_CHECKLIST_ID)] == [
        "complete_profile", "register_seminar", "say_hello",
    ]


def test_find_task():
    assert find_task(PREVIEW_CHECKLIST_ID, "say_hello").label == "Say hello in Parlêtre"
    assert find_task(PREVIEW_CHECKLIST_ID, "nope") is None
    assert get_checklist("no-such-checklist") == []


@pytest.mark.django_db
def test_resolved_task_shape_for_fresh_user(rf):
    user = get_user_model().objects.create_user(email="t@example.com", password="x")
    request = rf.get("/")
    request.user = user

    task = find_task(PREVIEW_CHECKLIST_ID, "complete_profile")
    d = task.resolved(user, request)

    assert d["id"] == "complete_profile"
    assert d["done"] is False          # no headshot/bio yet
    assert d["url"]                    # profile_edit reverses fine
    assert d["show_hint"] is True      # not done + has an anchor
    assert d["hint_key"] == "lsp-preview-tour-photo-hint"
    assert d["hint_placement"] == "below"


@pytest.mark.django_db
def test_resolved_done_hides_hint(rf):
    """A completed task ticks and stops showing its hint."""
    from io import BytesIO

    from PIL import Image

    from django.core.files.uploadedfile import SimpleUploadedFile

    user = get_user_model().objects.create_user(email="done@example.com", password="x")
    buf = BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format="PNG")
    user.profile.headshot = SimpleUploadedFile("h.png", buf.getvalue(), "image/png")
    user.profile.bio = "A short bio."
    user.profile.save()

    request = rf.get("/")
    request.user = user
    d = find_task(PREVIEW_CHECKLIST_ID, "complete_profile").resolved(user, request)
    assert d["done"] is True
    assert d["show_hint"] is False
