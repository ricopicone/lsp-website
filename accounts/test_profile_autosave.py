"""Background autosave of the profile editor's text fields."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


@pytest.mark.django_db
def test_autosave_persists_text_fields(client):
    user = get_user_model().objects.create_user(
        email="a@example.com", password="x", first_name="A", last_name="B",
    )
    client.force_login(user)
    resp = client.post(reverse("profile_autosave"), {
        "first_name": "Aldo", "last_name": "Moro", "bio": "A short bio.",
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    user.refresh_from_db()
    user.profile.refresh_from_db()
    assert user.first_name == "Aldo"
    assert user.profile.bio == "A short bio."


@pytest.mark.django_db
def test_autosave_requires_login(client):
    resp = client.post(reverse("profile_autosave"), {"first_name": "X"})
    assert resp.status_code in (302, 403)  # redirected to login (not saved)
