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


def test_pending_and_cancelled_registrations_are_denied():
    # Only PAID/COMPED grant access. An unpaid or cancelled row must not.
    from registrations.models import Registration

    ev = special_event(slug="statuses")
    for status in (
        Registration.Status.AWAITING_PAYMENT,
        Registration.Status.CANCELLED,
        Registration.Status.REFUNDED,
    ):
        u = user(f"{status}@x.test")
        register(u, ev, status=status)
        assert services.can_enter_event(ev, u) is False, status


def test_comped_registration_is_admitted():
    # Comping is the do-not-over-automate escape hatch; it must open the room.
    from registrations.models import Registration

    ev = special_event(slug="comped")
    u = user("comp@x.test")
    register(u, ev, status=Registration.Status.COMPED)
    assert services.can_enter_event(ev, u) is True


def test_treasurer_suspension_cuts_room_access():
    # Profile.seminar_access_suspended is a manual, audited treasurer action;
    # has_access_registrant honours it, so the room must too.
    ev = special_event(slug="suspended")
    u = user("susp@x.test")
    register(u, ev)
    assert services.can_enter_event(ev, u) is True
    u.profile.seminar_access_suspended = True
    u.profile.save(update_fields=["seminar_access_suspended"])
    u.refresh_from_db()
    assert services.can_enter_event(ev, u) is False


def test_anonymous_visitor_is_redirected_to_login_not_403(client):
    # Gated GET pages redirect anonymous users to login with ?next= — only
    # signed-in non-members get a 403. Covered for seminars; this is the
    # event-owned-room path.
    ev = special_event(slug="anon-event")
    resp = client.get(f"/events/{ev.slug}/room/")
    assert resp.status_code == 302
    assert "/accounts/login" in resp.url or "/login" in resp.url


def test_spotlight_mutes_attendees_but_never_the_speaker():
    """The speaker keeps A/V; attendees land muted + camera-off, softly.

    The speaker is a ``member_speaker``, not faculty — a PC-organized event
    shares the Programming Committee's workgroup, so making a presenter faculty
    there would put them on the PC roster and hand them every PC event (#463).
    This is exactly how Working with Masochism is configured on prod.
    """
    ev = special_event(slug="spot-matrix")
    ev.speaker_spotlight = True
    ev.save(update_fields=["speaker_spotlight"])
    speaker = user("spot-speaker@x.test")
    ev.member_speakers.add(speaker)
    attendee = user("spot-att@x.test")
    register(attendee, ev)
    assert services.is_owner(ev, speaker) is True    # moderator controls
    assert services.can_enter_event(ev, speaker) is True  # without registering
    assert services.spotlight_start_off(ev, services.is_owner(ev, speaker)) is False
    assert services.spotlight_start_off(ev, services.is_owner(ev, attendee)) is True


@daily_on
def test_spotlight_reaches_the_minted_token(client, monkeypatch):
    # The flag is worthless unless it actually lands on the token.
    seen: dict = {}
    monkeypatch.setattr("video.daily.get_room", lambda name: None)
    monkeypatch.setattr(
        "video.daily.create_room",
        lambda name, *, properties=None: {"name": name, "url": f"https://x/{name}"},
    )
    monkeypatch.setattr(
        "video.daily.create_meeting_token", lambda **kw: seen.update(kw) or "tok"
    )
    ev = special_event(slug="spot-token")
    ev.speaker_spotlight = True
    ev.save(update_fields=["speaker_spotlight"])
    attendee = user("spot-tok@x.test")
    register(attendee, ev)
    client.force_login(attendee)
    assert client.get(f"/events/{ev.slug}/room/").status_code == 200
    assert seen.get("start_audio_off") is True
    assert seen.get("start_video_off") is True


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
