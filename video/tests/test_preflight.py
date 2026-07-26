from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from video import services

from .factories import daily_on, register, special_event, user

pytestmark = pytest.mark.django_db


@daily_on
def test_preflight_is_read_only_by_default(monkeypatch):
    # The whole point: running the check must never provision the room, because
    # creating a room freezes its property set at that moment.
    created: list = []
    monkeypatch.setattr("video.daily.get_room", lambda name: None)
    monkeypatch.setattr(
        "video.daily.create_room",
        lambda name, *, properties=None: created.append(name) or {"name": name},
    )
    monkeypatch.setattr("video.daily.get_presence", lambda: {})
    ev = special_event(slug="pf-readonly")
    out = StringIO()
    call_command("event_video_preflight", ev.slug, stdout=out)
    assert created == []
    assert "not provisioned" in out.getvalue().lower()


@daily_on
def test_preflight_provisions_only_when_asked(monkeypatch):
    created: list = []
    monkeypatch.setattr("video.daily.get_room", lambda name: None)
    monkeypatch.setattr(
        "video.daily.create_room",
        lambda name, *, properties=None: created.append(name)
        or {"name": name, "url": f"https://x/{name}"},
    )
    monkeypatch.setattr("video.daily.get_presence", lambda: {})
    ev = special_event(slug="pf-provision")
    out = StringIO()
    call_command("event_video_preflight", ev.slug, "--provision", stdout=out)
    assert created == ["lsp-event-pf-provision"]


@daily_on
def test_preflight_reports_live_room_property_drift(monkeypatch):
    # It must compare against the LIVE config, not the intended properties.
    ev = special_event(slug="pf-drift")
    config = dict(services._desired_properties(ev))
    config["enable_hand_raising"] = False
    monkeypatch.setattr(
        "video.daily.get_room",
        lambda name: {"name": name, "url": f"https://x/{name}", "config": config},
    )
    monkeypatch.setattr("video.daily.get_presence", lambda: {})
    ev.speaker_spotlight = True
    ev.save(update_fields=["speaker_spotlight"])
    out = StringIO()
    with pytest.raises(SystemExit):
        call_command("event_video_preflight", ev.slug, stdout=out)
    assert "enable_hand_raising" in out.getvalue()


@daily_on
def test_preflight_passes_a_correctly_configured_event(monkeypatch):
    ev = special_event(slug="pf-ok")
    ev.speaker_spotlight = True
    ev.save(update_fields=["speaker_spotlight"])
    speaker = user("pf-speaker@x.test")
    speaker.profile.email_verified_at = "2026-01-01T00:00:00+00:00"
    speaker.profile.save(update_fields=["email_verified_at"])
    ev.member_speakers.add(speaker)
    register(user("pf-att@x.test"), ev)
    config = dict(services._desired_properties(ev))
    monkeypatch.setattr(
        "video.daily.get_room",
        lambda name: {"name": name, "url": f"https://x/{name}", "config": config},
    )
    monkeypatch.setattr("video.daily.get_presence", lambda: {})
    out = StringIO()
    call_command("event_video_preflight", ev.slug, stdout=out)  # no SystemExit
    assert "FAIL" not in out.getvalue()


@daily_on
def test_preflight_flags_a_speaker_who_cannot_enter(monkeypatch):
    # The failure that would actually ruin the event: the speaker can't get in.
    ev = special_event(slug="pf-locked")
    ev.speaker_spotlight = True
    ev.save(update_fields=["speaker_spotlight"])
    speaker = user("pf-locked@x.test")
    speaker.profile.email_verified_at = "2026-01-01T00:00:00+00:00"
    speaker.profile.save(update_fields=["email_verified_at"])
    ev.member_speakers.add(speaker)
    speaker.is_active = False
    speaker.save(update_fields=["is_active"])
    config = dict(services._desired_properties(ev))
    monkeypatch.setattr(
        "video.daily.get_room",
        lambda name: {"name": name, "url": f"https://x/{name}", "config": config},
    )
    monkeypatch.setattr("video.daily.get_presence", lambda: {})
    out = StringIO()
    with pytest.raises(SystemExit):
        call_command("event_video_preflight", ev.slug, stdout=out)
    assert "inactive" in out.getvalue()


def test_preflight_fails_loudly_when_daily_is_disabled():
    # Default settings have DAILY_ENABLED false — say so rather than pretending.
    ev = special_event(slug="pf-off")
    out = StringIO()
    with pytest.raises(SystemExit):
        call_command("event_video_preflight", ev.slug, stdout=out)
    assert "disabled" in out.getvalue().lower()


def test_preflight_rejects_an_unknown_slug():
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("event_video_preflight", "no-such-event", stdout=StringIO())
