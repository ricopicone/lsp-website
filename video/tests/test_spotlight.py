"""Speaker spotlight: attendees join a spotlighted event with A/V off (task #463)."""
from __future__ import annotations

from datetime import date

import pytest

from accounts.models import User
from events.models import Event
from video import services
from video.models import DailyRoom

pytestmark = pytest.mark.django_db


def _event(spotlight=False):
    return Event.objects.create(
        title="Talk", slug=f"spot-{spotlight}",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2030, 9, 1), end_date=date(2030, 9, 1),
        published=True, status=Event.Status.OPEN,
        speaker_spotlight=spotlight,
    )


def test_mint_token_start_off_passes_av_flags(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "video.daily.create_meeting_token",
        lambda **kw: captured.update(kw) or "tok",
    )
    room = DailyRoom.objects.create(
        event=_event(), name="lsp-event-x", url="https://d/lsp-event-x",
    )
    u = User.objects.create_user(email="a@x.test")
    services.mint_token(room, u, is_owner=False, start_off=True)
    assert captured["start_audio_off"] is True
    assert captured["start_video_off"] is True


def test_mint_token_without_start_off_leaves_av_on(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "video.daily.create_meeting_token",
        lambda **kw: captured.update(kw) or "tok",
    )
    room = DailyRoom.objects.create(
        event=_event(), name="lsp-event-y", url="https://d/lsp-event-y",
    )
    u = User.objects.create_user(email="b@x.test")
    services.mint_token(room, u, is_owner=False, start_off=False)
    assert captured.get("start_audio_off", False) is False
    assert captured.get("start_video_off", False) is False


def test_spotlight_start_off_only_for_nonowner_of_spotlit_event():
    on = _event(spotlight=True)
    off = _event(spotlight=False)
    # Attendee (non-owner) of a spotlit event → start off.
    assert services.spotlight_start_off(on, is_owner_flag=False) is True
    # The speaker/host (owner) is never started off.
    assert services.spotlight_start_off(on, is_owner_flag=True) is False
    # Spotlight off → nobody started off.
    assert services.spotlight_start_off(off, is_owner_flag=False) is False


def test_spotlight_start_off_false_for_workgroup_owner():
    from workgroups.models import Workgroup, build_workgroup
    wg = build_workgroup(Workgroup.Kind.SEMINAR, name="Sem", slug="sem-spot")
    assert services.spotlight_start_off(wg, is_owner_flag=False) is False
