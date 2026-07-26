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


def _missing(name):
    """get_room stub: the room does not exist on Daily."""
    return None


@daily_on
def test_ensure_room_creates_when_missing(monkeypatch):
    calls: list = []
    monkeypatch.setattr("video.daily.get_room", _missing)
    monkeypatch.setattr("video.daily.create_room", _fake_create_room(calls))
    wg = seminar().ensure_workgroup()
    room = services.ensure_room(wg)
    assert isinstance(room, DailyRoom)
    assert room.provider_created is True
    assert room.name == f"lsp-{wg.slug}"
    assert len(calls) == 1


@daily_on
def test_ensure_room_reuses_existing_daily_room(monkeypatch):
    create_calls: list = []
    wg = seminar().ensure_workgroup()
    monkeypatch.setattr(
        "video.daily.get_room",
        lambda name: {"name": name, "url": f"https://lsp.daily.co/{name}",
                      "config": dict(services._desired_properties(wg))},
    )
    monkeypatch.setattr("video.daily.create_room", _fake_create_room(create_calls))
    room = services.ensure_room(wg)
    again = services.ensure_room(wg)
    assert again.pk == room.pk
    assert create_calls == []  # Daily already has the room → never recreated


@daily_on
def test_ensure_room_recreates_room_deleted_on_daily(monkeypatch):
    # The DB row exists + provider_created, but the Daily room was deleted
    # (e.g. cleaned up in the dashboard). ensure_room must self-heal.
    wg = seminar().ensure_workgroup()
    DailyRoom.objects.create(
        workgroup=wg, name=f"lsp-{wg.slug}", url="https://x/y", provider_created=True
    )
    create_calls: list = []
    monkeypatch.setattr("video.daily.get_room", _missing)
    monkeypatch.setattr("video.daily.create_room", _fake_create_room(create_calls))
    room = services.ensure_room(wg)
    assert len(create_calls) == 1  # recreated on Daily's side
    assert room.provider_created is True


@daily_on
def test_ensure_room_recording_available_not_auto(monkeypatch):
    # Recording is *available* to hosts ("cloud"), not auto-on.
    calls: list = []
    monkeypatch.setattr("video.daily.get_room", _missing)
    monkeypatch.setattr("video.daily.create_room", _fake_create_room(calls))
    wg = seminar().ensure_workgroup()
    services.ensure_room(wg)
    assert calls[0]["properties"]["enable_recording"] == "cloud"


@daily_on
def test_ensure_room_recording_off_disables_button(monkeypatch):
    # recording_mode=off removes the Record button (enable_recording: False).
    calls: list = []
    monkeypatch.setattr("video.daily.get_room", _missing)
    monkeypatch.setattr("video.daily.create_room", _fake_create_room(calls))
    wg = seminar().ensure_workgroup()
    wg.recording_mode = "off"
    wg.save(update_fields=["recording_mode"])
    services.ensure_room(wg)
    assert calls[0]["properties"]["enable_recording"] is False


@daily_on
def test_ensure_room_reconciles_recording_toggle(monkeypatch):
    # An existing Daily room with recording on gets toggled off when the owner
    # switches to recording_mode=off.
    monkeypatch.setattr(
        "video.daily.get_room",
        lambda name: {"name": name, "url": f"https://x/{name}",
                      "config": {"enable_recording": "cloud"}},
    )
    updates: list = []
    monkeypatch.setattr("video.daily.update_room", lambda name, props: updates.append(props))
    monkeypatch.setattr("video.daily.create_room", _fake_create_room([]))
    wg = seminar().ensure_workgroup()
    wg.recording_mode = "off"
    wg.save(update_fields=["recording_mode"])
    services.ensure_room(wg)
    assert updates and updates[0]["enable_recording"] is False


@daily_on
def test_ensure_room_does_not_update_when_config_matches(monkeypatch):
    # No drift -> no write. Guards against an update call on every single join.
    wg = seminar().ensure_workgroup()
    config = dict(services._desired_properties(wg))
    monkeypatch.setattr(
        "video.daily.get_room",
        lambda name: {"name": name, "url": f"https://x/{name}", "config": config},
    )
    updates: list = []
    monkeypatch.setattr(
        "video.daily.update_room", lambda name, props: updates.append(props) or {}
    )
    services.ensure_room(wg)
    assert updates == []


@daily_on
def test_ensure_room_tolerates_daily_string_zero_for_recording(monkeypatch):
    # Daily stores a falsy enable_recording as the STRING "0". A naive equality
    # check reads that as permanent drift and rewrites the room on every join.
    wg = seminar().ensure_workgroup()
    wg.recording_mode = "off"
    wg.save(update_fields=["recording_mode"])
    config = dict(services._desired_properties(wg))
    assert config["enable_recording"] is False
    config["enable_recording"] = "0"  # what Daily actually returns
    monkeypatch.setattr(
        "video.daily.get_room",
        lambda name: {"name": name, "url": f"https://x/{name}", "config": config},
    )
    updates: list = []
    monkeypatch.setattr(
        "video.daily.update_room", lambda name, props: updates.append(props) or {}
    )
    services.ensure_room(wg)
    assert updates == []


@daily_on
def test_ensure_room_reconciles_every_drifted_property(monkeypatch):
    # R1: a room created before a property existed must receive it — the old
    # code only ever reconciled enable_recording.
    wg = seminar().ensure_workgroup()
    config = dict(services._desired_properties(wg))
    config.pop("enable_people_ui")   # room predates the property
    config["enable_chat"] = False    # and one drifted underneath us
    monkeypatch.setattr(
        "video.daily.get_room",
        lambda name: {"name": name, "url": f"https://x/{name}", "config": config},
    )
    updates: list = []
    monkeypatch.setattr(
        "video.daily.update_room",
        lambda name, props: updates.append(props)
        or {"name": name, "url": f"https://x/{name}"},
    )
    services.ensure_room(wg)
    assert updates == [{"enable_people_ui": True, "enable_chat": True}]


def test_the_daily_api_is_blocked_in_tests():
    # The conftest guard must actually bite. Without it an unstubbed call goes
    # out to api.daily.co for real, 401s on the fake key, and several call sites
    # swallow that — so the suite stays green while doing network I/O.
    from video import daily

    with pytest.raises(AssertionError, match="must not call the Daily API"):
        daily.get_room("anything")


def test_ensure_room_returns_none_when_disabled():
    # Default settings: DAILY_ENABLED is False -> no-op.
    wg = seminar().ensure_workgroup()
    assert services.ensure_room(wg) is None


@daily_on
def test_mint_token_passes_owner_flag(monkeypatch):
    captured: dict = {}

    def _fake_token(*, room_name, user_name="", is_owner=False, exp=None, **kwargs):
        captured.update(room_name=room_name, user_name=user_name, is_owner=is_owner)
        return "tok-123"

    monkeypatch.setattr("video.daily.get_room", _missing)
    monkeypatch.setattr("video.daily.create_room", _fake_create_room([]))
    monkeypatch.setattr("video.daily.create_meeting_token", _fake_token)
    wg = seminar().ensure_workgroup()
    room = services.ensure_room(wg)
    teacher = user("t@x.test", is_faculty=True)

    token = services.mint_token(room, teacher, is_owner=True)
    assert token == "tok-123"
    assert captured["is_owner"] is True
    assert captured["room_name"] == room.name
