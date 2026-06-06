"""One-off events (special events, Days of Assembly, Working Days, Scholarly
Seminars) own their own Daily room rather than sharing the Programming
Committee's workgroup room. Offering events still meet in their workgroup room."""
from __future__ import annotations

import pytest

from video import services
from video.models import DailyRoom

from .factories import daily_on, register, seminar, special_event, user

pytestmark = pytest.mark.django_db


def _stub_daily(monkeypatch, calls):
    monkeypatch.setattr("video.daily.get_room", lambda name: None)
    monkeypatch.setattr(
        "video.daily.create_room",
        lambda name, *, properties=None: calls.append(
            {"name": name, "properties": properties or {}}
        )
        or {"name": name, "url": f"https://lsp.daily.co/{name}"},
    )


@daily_on
def test_special_event_gets_its_own_room(monkeypatch):
    calls: list = []
    _stub_daily(monkeypatch, calls)
    ev = special_event(slug="masoch")
    room = services.ensure_room(ev)
    assert isinstance(room, DailyRoom)
    assert room.event_id == ev.id
    assert room.workgroup_id is None and room.channel_id is None
    assert room.name == "lsp-event-masoch"  # its own room, not the PC's


@daily_on
def test_offering_event_still_uses_workgroup_room(monkeypatch):
    calls: list = []
    _stub_daily(monkeypatch, calls)
    wg = seminar(slug="sem-room").ensure_workgroup()
    room = services.ensure_room(wg)
    assert room.workgroup_id == wg.id
    assert room.name == f"lsp-{wg.slug}"


@daily_on
def test_special_event_recording_off_removes_button(monkeypatch):
    calls: list = []
    _stub_daily(monkeypatch, calls)
    ev = special_event(slug="no-rec")
    ev.recording_mode = "off"
    ev.save(update_fields=["recording_mode"])
    services.ensure_room(ev)
    assert calls[0]["properties"]["enable_recording"] is False


def test_can_enter_event_registrant_yes_outsider_no():
    ev = special_event(slug="enter")
    paid = user("paid@x.test")
    register(paid, ev)
    outsider = user("out@x.test")
    host = user("host@x.test", is_faculty=True)
    ev.add_faculty(host)
    assert services.can_enter_event(ev, paid) is True
    assert services.can_enter_event(ev, host) is True   # event host
    assert services.can_enter_event(ev, outsider) is False


def test_recording_in_event_room_binds_to_event():
    # A recording made in a special event's own room resolves to that event, so
    # its visibility keys off the event's registrants (not the PC workgroup).
    ev = special_event(slug="rec-bind")
    room = DailyRoom.objects.create(
        event=ev, name="lsp-event-rec-bind", url="https://x/lsp-event-rec-bind",
        provider_created=True,
    )
    event, title = services._recording_event_and_title(room)
    assert event == ev
    assert title == ev.title


@daily_on
def test_event_room_view_provisions_own_room(client, monkeypatch):
    calls: list = []
    _stub_daily(monkeypatch, calls)
    monkeypatch.setattr("video.daily.create_meeting_token", lambda **kw: "tok")
    ev = special_event(slug="view-room")
    paid = user("v@x.test")
    register(paid, ev)
    client.force_login(paid)
    resp = client.get(f"/events/{ev.slug}/room/")
    assert resp.status_code == 200
    room = DailyRoom.objects.get(event=ev)
    assert room.name == "lsp-event-view-room"
    # A non-registrant outsider is denied.
    outsider = user("vo@x.test")
    client.force_login(outsider)
    assert client.get(f"/events/{ev.slug}/room/").status_code == 403
