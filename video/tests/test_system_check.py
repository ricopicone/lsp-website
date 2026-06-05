from __future__ import annotations

import pytest
from django.urls import reverse

from video import services

from .factories import daily_on, seminar, user

pytestmark = pytest.mark.django_db


@pytest.fixture
def _capture_daily(monkeypatch):
    calls = {"rooms": []}

    def fake_create_room(name, properties=None):
        calls["rooms"].append({"name": name, "properties": properties or {}})
        return {"name": name, "url": f"https://lsp.daily.co/{name}"}

    monkeypatch.setattr("video.daily.create_room", fake_create_room)
    monkeypatch.setattr("video.daily.create_meeting_token", lambda **kw: "tok")
    return calls


@daily_on
def test_system_check_throwaway_room_auto_closes(_capture_daily):
    from django.test import RequestFactory

    req = RequestFactory().get("/")
    req.user = user("u@x.test")
    ctx = services.system_check_context(req)
    assert ctx["room_url"].startswith("https://lsp.daily.co/lsp-check-")
    assert ctx["room_token"] == "tok"
    props = _capture_daily["rooms"][0]["properties"]
    assert "exp" in props and props["eject_at_room_exp"] is True
    assert props["enable_prejoin_ui"] is True


def test_system_check_unavailable_when_disabled():
    from django.test import RequestFactory

    req = RequestFactory().get("/")
    req.user = user("u2@x.test")
    assert services.system_check_context(req) == {"room_unavailable": True}


@daily_on
def test_system_check_view_requires_login(client):
    resp = client.get(reverse("video:system_check"))
    assert resp.status_code == 302  # redirect to login


@daily_on
def test_system_check_view_renders(client, _capture_daily):
    client.force_login(user("u3@x.test"))
    resp = client.get(reverse("video:system_check"))
    assert resp.status_code == 200
    assert b"Test your video" in resp.content
    assert b"room-token" in resp.content


@daily_on
def test_rooms_enable_chat_and_people_ui(monkeypatch):
    captured = {}
    monkeypatch.setattr("video.daily.get_room", lambda name: None)  # forces create
    monkeypatch.setattr(
        "video.daily.create_room",
        lambda name, properties=None: captured.update(properties or {}) or {"url": f"x/{name}"},
    )
    wg = seminar().ensure_workgroup()
    services.ensure_room(wg)
    assert captured["enable_chat"] is True
    assert captured["enable_people_ui"] is True
    assert captured["enable_recording"] == "cloud"
