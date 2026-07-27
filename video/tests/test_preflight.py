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


def _invited_external_speaker(event, *, expires_in_days, email="hook@x.test"):
    """An external presenter who has been sent a login invitation but hasn't
    activated yet: no usable password, unverified email, valid pending invite."""
    from datetime import timedelta

    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from events.models import Speaker, SpeakerInvitation

    u = get_user_model().objects.create_user(email=email)  # unusable password
    sp = Speaker.objects.create(
        name="Derek Hook", slug=f"dh-{event.slug}", email=email, user=u
    )
    event.speakers.add(sp)
    SpeakerInvitation.objects.create(
        speaker=sp, user=u,
        expires_at=timezone.now() + timedelta(days=expires_in_days),
    )
    return sp, u


def _stub_room(monkeypatch, event):
    config = dict(services._desired_properties(event))
    monkeypatch.setattr(
        "video.daily.get_room",
        lambda name: {"name": name, "url": f"https://x/{name}", "config": config},
    )
    monkeypatch.setattr("video.daily.get_presence", lambda: {})


@daily_on
def test_pending_speaker_invitation_is_a_warning_not_a_failure(monkeypatch):
    # An invited external presenter who hasn't activated yet is the *expected*
    # state, not a broken one. Reporting FAIL here trains people to ignore the
    # pre-flight.
    from datetime import timedelta

    from django.utils import timezone

    from events.models import Session

    ev = special_event(slug="pf-invited")
    ev.speaker_spotlight = True
    ev.save(update_fields=["speaker_spotlight"])
    start = timezone.now() + timedelta(days=10)
    Session.objects.create(
        event=ev, sequence=1, start_at=start, end_at=start + timedelta(hours=2)
    )
    _invited_external_speaker(ev, expires_in_days=30)
    _stub_room(monkeypatch, ev)
    out = StringIO()
    call_command("event_video_preflight", ev.slug, stdout=out)  # no SystemExit
    text = out.getvalue()
    assert "FAIL" not in text
    assert "invitation pending" in text


@daily_on
def test_invitation_expiring_before_the_event_is_a_failure(monkeypatch):
    # The trap: a 30-day invitation sent for an event more than 30 days out
    # lapses before the speaker ever uses it — and because the account has no
    # usable password, Django's password reset silently skips them, so they
    # cannot self-recover.
    from datetime import timedelta

    from django.utils import timezone

    from events.models import Session

    ev = special_event(slug="pf-lapses")
    start = timezone.now() + timedelta(days=40)
    Session.objects.create(
        event=ev, sequence=1, start_at=start, end_at=start + timedelta(hours=2)
    )
    _invited_external_speaker(ev, expires_in_days=30)
    _stub_room(monkeypatch, ev)
    out = StringIO()
    with pytest.raises(SystemExit):
        call_command("event_video_preflight", ev.slug, stdout=out)
    text = out.getvalue().lower()
    assert "expires" in text
    assert "before the event" in text
    assert "refresh it" in text


@daily_on
def test_unactivated_speaker_with_no_invitation_is_a_failure(monkeypatch):
    # No usable password and nothing pending: genuinely stuck, and password
    # reset will not rescue them.
    from django.contrib.auth import get_user_model

    from events.models import Speaker

    ev = special_event(slug="pf-stranded")
    u = get_user_model().objects.create_user(email="stranded@x.test")
    ev.speakers.add(
        Speaker.objects.create(name="Stranded", slug="stranded", user=u)
    )
    _stub_room(monkeypatch, ev)
    out = StringIO()
    with pytest.raises(SystemExit):
        call_command("event_video_preflight", ev.slug, stdout=out)
    assert "no valid invitation" in out.getvalue()


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
