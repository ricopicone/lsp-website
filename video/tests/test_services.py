from __future__ import annotations

import pytest

from video import services
from video.models import DailyRoom

from .factories import daily_on, seminar, user

pytestmark = pytest.mark.django_db


def _fake_create_room(calls):
    def _inner(name, *, properties=None):
        calls.append({"name": name, "properties": properties or {}})
        return {"name": name, "url": f"https://lsp.daily.co/{name}"}
    return _inner


@daily_on
def test_ensure_room_is_idempotent(monkeypatch):
    calls: list = []
    monkeypatch.setattr("video.daily.create_room", _fake_create_room(calls))
    event = seminar()
    wg = event.ensure_workgroup()

    room = services.ensure_room(wg)
    assert isinstance(room, DailyRoom)
    assert room.provider_created is True
    assert room.name == f"lsp-{wg.slug}"

    # Second call reuses the row — no second provider hit.
    again = services.ensure_room(wg)
    assert again.pk == room.pk
    assert len(calls) == 1


@daily_on
def test_ensure_room_disables_recording(monkeypatch):
    calls: list = []
    monkeypatch.setattr("video.daily.create_room", _fake_create_room(calls))
    wg = seminar().ensure_workgroup()
    services.ensure_room(wg)
    assert calls[0]["properties"]["enable_recording"] is False


def test_ensure_room_returns_none_when_disabled():
    # Default settings: DAILY_ENABLED is False -> no-op.
    wg = seminar().ensure_workgroup()
    assert services.ensure_room(wg) is None


@daily_on
def test_mint_token_passes_owner_flag(monkeypatch):
    captured: dict = {}

    def _fake_token(*, room_name, user_name="", is_owner=False, exp=None):
        captured.update(room_name=room_name, user_name=user_name, is_owner=is_owner)
        return "tok-123"

    monkeypatch.setattr("video.daily.create_room", _fake_create_room([]))
    monkeypatch.setattr("video.daily.create_meeting_token", _fake_token)
    wg = seminar().ensure_workgroup()
    room = services.ensure_room(wg)
    teacher = user("t@x.test", is_faculty=True)

    token = services.mint_token(room, teacher, is_owner=True)
    assert token == "tok-123"
    assert captured["is_owner"] is True
    assert captured["room_name"] == room.name
