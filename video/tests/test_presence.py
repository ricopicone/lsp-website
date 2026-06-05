from __future__ import annotations

import pytest
from django.core.cache import cache

from video import daily, services

from .factories import daily_on, seminar


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = ""

    def json(self):
        return self._payload


@daily_on
def test_get_presence_parses_data_wrapper(monkeypatch):
    monkeypatch.setattr(
        "video.daily.requests.get",
        lambda *a, **k: _Resp({"total_count": 1, "data": {"lsp-x": [{"userName": "A"}]}}),
    )
    assert daily.get_presence() == {"lsp-x": [{"userName": "A"}]}


@daily_on
def test_get_presence_parses_flat_shape(monkeypatch):
    monkeypatch.setattr(
        "video.daily.requests.get",
        lambda *a, **k: _Resp({"total_count": 1, "lsp-x": [{"userName": "A"}]}),
    )
    assert daily.get_presence() == {"lsp-x": [{"userName": "A"}]}


@pytest.mark.django_db
@daily_on
def test_room_participant_count_and_live_names(monkeypatch):
    wg = seminar().ensure_workgroup()
    from video.models import DailyRoom

    room = DailyRoom.objects.create(
        workgroup=wg, name="lsp-sem", url="https://lsp.daily.co/lsp-sem", provider_created=True
    )
    monkeypatch.setattr(
        "video.daily.get_presence",
        lambda: {"lsp-sem": [{"userName": "A"}], "lsp-empty": []},
    )
    assert services.room_participant_count(room) == 1
    assert services.live_room_names() == {"lsp-sem"}


def test_room_participant_count_none_skips_fetch(monkeypatch):
    called = []
    monkeypatch.setattr("video.daily.get_presence", lambda: called.append(1) or {})
    assert services.room_participant_count(None) == 0
    assert called == []


@daily_on
def test_presence_is_cached(monkeypatch):
    calls = []

    def _fake():
        calls.append(1)
        return {"lsp-x": [{"userName": "A"}]}

    monkeypatch.setattr("video.daily.get_presence", _fake)
    services.presence_map()
    services.presence_map()
    assert len(calls) == 1  # second call served from cache


def test_participant_names_dedupes_and_keeps_order():
    people = [
        {"userName": "Rico Picone"}, {"userName": "Alice"},
        {"userName": "rico picone"},  # dup (case-insensitive)
        {"userName": ""}, {"user_name": "Bob"},  # blank skipped, fallback key
    ]
    assert services.participant_names(people) == ["Rico Picone", "Alice", "Bob"]


@pytest.mark.django_db
@daily_on
def test_presence_names_for_room(monkeypatch):
    wg = seminar().ensure_workgroup()
    from video.models import DailyRoom

    room = DailyRoom.objects.create(
        workgroup=wg, name="lsp-sem", url="https://lsp.daily.co/lsp-sem", provider_created=True
    )
    monkeypatch.setattr(
        "video.daily.get_presence", lambda: {"lsp-sem": [{"userName": "Rico Picone"}]}
    )
    assert services.presence_names(room) == ["Rico Picone"]
    assert services.presence_names(None) == []


def test_presence_empty_when_disabled(monkeypatch):
    # Daily off (default settings) -> no fetch, empty map.
    called = []
    monkeypatch.setattr("video.daily.get_presence", lambda: called.append(1) or {})
    assert services.presence_map() == {}
    assert called == []
