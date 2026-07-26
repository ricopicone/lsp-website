"""Test-wide guard: the video suite must never reach api.daily.co.

Every Daily-touching test stubs the ``video.daily`` function it exercises, but
an *unstubbed* path used to sail straight out to the network on a fake API key
and come back a 401 — which several call sites swallow, so the test would go
green (or fail for the wrong reason) while having made a real HTTP request.

This fixture replaces the ``requests`` module inside ``video.daily`` with one
that raises, turning any un-stubbed call into a loud, specific failure naming
the function to stub.
"""
from __future__ import annotations

import pytest


class _BlockedRequests:
    """Stands in for ``requests`` inside ``video.daily`` during tests."""

    def _blocked(self, method):
        def _inner(*args, **kwargs):
            target = args[0] if args else kwargs.get("url", "?")
            raise AssertionError(
                f"The video tests must not call the Daily API. A test reached "
                f"{method.upper()} {target} without stubbing it — monkeypatch the "
                f"relevant video.daily.* function (get_room / create_room / "
                f"update_room / delete_room / create_meeting_token / get_presence / "
                f"get_recording / recording_access_link / delete_recording)."
            )
        return _inner

    def __getattr__(self, name):
        return self._blocked(name)


@pytest.fixture(autouse=True)
def _no_real_daily_calls(monkeypatch):
    monkeypatch.setattr("video.daily.requests", _BlockedRequests())
