from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from django.test import override_settings
from django.urls import reverse

from accounts.models import Profile
from video import daily
from video.models import DailyRoom, Recording

from .factories import register, seminar, user

pytestmark = pytest.mark.django_db

_SECRET = base64.b64encode(b"recording-webhook-secret").decode()
webhook_on = override_settings(DAILY_WEBHOOK_SECRET=_SECRET)


def _sign(timestamp: str, body: bytes) -> str:
    key = base64.b64decode(_SECRET)
    mac = hmac.new(key, timestamp.encode() + b"." + body, hashlib.sha256).digest()
    return base64.b64encode(mac).decode()


# --- webhook signature ---

@webhook_on
def test_verify_webhook_accepts_valid_rejects_tampered():
    body = b'{"type":"recording.started"}'
    sig = _sign("100", body)
    assert daily.verify_webhook("100", body, sig) is True
    assert daily.verify_webhook("100", body + b"x", sig) is False
    assert daily.verify_webhook("100", body, "nope") is False


def test_verify_webhook_false_without_secret():
    assert daily.verify_webhook("1", b"{}", "x") is False


@webhook_on
def test_webhook_rejects_bad_signature(client):
    resp = client.post(
        reverse("video:recording_webhook"), data=b"{}", content_type="application/json",
        HTTP_X_WEBHOOK_TIMESTAMP="1", HTTP_X_WEBHOOK_SIGNATURE="bad",
    )
    assert resp.status_code == 400


@webhook_on
def test_webhook_unsigned_handshake_returns_200(client):
    # Daily's registration liveness ping carries no signature.
    resp = client.post(
        reverse("video:recording_webhook"), data=b"{}", content_type="application/json",
    )
    assert resp.status_code == 200


@webhook_on
def test_webhook_ready_creates_recording_idempotently(client):
    wg = seminar().ensure_workgroup()
    DailyRoom.objects.create(
        workgroup=wg, name="lsp-sem", url="https://x/lsp-sem", provider_created=True
    )
    body = json.dumps({
        "type": "recording.ready-to-download",
        "payload": {"recording_id": "rec-1", "room_name": "lsp-sem",
                    "duration": 120, "s3_key": "k/rec-1.mp4"},
    }).encode()
    ts = "1700000000"

    def post():
        return client.post(
            reverse("video:recording_webhook"), data=body, content_type="application/json",
            HTTP_X_WEBHOOK_TIMESTAMP=ts, HTTP_X_WEBHOOK_SIGNATURE=_sign(ts, body),
        )

    assert post().status_code == 200
    assert post().status_code == 200  # idempotent
    recs = Recording.objects.filter(daily_recording_id="rec-1")
    assert recs.count() == 1
    rec = recs.get()
    assert rec.status == Recording.Status.READY
    assert rec.duration_seconds == 120 and rec.s3_key == "k/rec-1.mp4"


# --- visibility ---

def _recording(wg, *, content, listing=None):
    room = DailyRoom.objects.create(
        workgroup=wg, name="lsp-vz", url="https://x/lsp-vz", provider_created=True
    )
    return Recording.objects.create(
        daily_recording_id="rz", room=room, status=Recording.Status.READY,
        content_visibility=content, listing_visibility=listing or content,
        event=wg.primary_event(),
    )


def test_visibility_members_vs_nonmember():
    wg = seminar().ensure_workgroup()
    rec = _recording(wg, content=Recording.Visibility.MEMBERS)
    member = user("m@x.test")
    outsider = user("o@x.test")
    outsider.profile.role = Profile.Role.EXTERNAL
    outsider.profile.save()
    assert rec.content_visible_to(member) is True
    assert rec.content_visible_to(outsider) is False


def test_visibility_registrants_only():
    event = seminar()
    wg = event.ensure_workgroup()
    rec = _recording(wg, content=Recording.Visibility.REGISTRANTS)
    paid = user("p@x.test")
    register(paid, event)  # PAID
    member = user("m2@x.test")  # member, not registered
    assert rec.content_visible_to(paid) is True
    assert rec.content_visible_to(member) is False


def test_visibility_staff_only_needs_host():
    event = seminar()
    wg = event.ensure_workgroup()
    rec = _recording(wg, content=Recording.Visibility.STAFF)
    member = user("m3@x.test")
    teacher = user("t@x.test", is_faculty=True)
    event.add_faculty(teacher)
    assert rec.content_visible_to(member) is False
    assert rec.content_visible_to(teacher) is True


def test_content_cannot_exceed_listing():
    from django.core.exceptions import ValidationError

    wg = seminar().ensure_workgroup()
    rec = _recording(wg, content=Recording.Visibility.PUBLIC, listing=Recording.Visibility.MEMBERS)
    with pytest.raises(ValidationError):
        rec.clean()


# --- player view ---

def test_recording_play_gated(client, monkeypatch):
    wg = seminar().ensure_workgroup()
    rec = _recording(wg, content=Recording.Visibility.MEMBERS)
    monkeypatch.setattr(Recording, "playable_url", lambda self: "https://x/play.mp4")
    member = user("m4@x.test")
    outsider = user("o2@x.test")
    outsider.profile.role = Profile.Role.EXTERNAL
    outsider.profile.save()

    client.force_login(outsider)
    assert client.get(reverse("video:recording_play", args=[rec.pk])).status_code == 403
    client.force_login(member)
    resp = client.get(reverse("video:recording_play", args=[rec.pk]))
    assert resp.status_code == 200
    assert b"play.mp4" in resp.content


# --- retention ---

def test_purge_old_recordings_dry_run(capsys):
    from datetime import timedelta

    from django.core.management import call_command
    from django.utils import timezone

    wg = seminar().ensure_workgroup()
    old = _recording(wg, content=Recording.Visibility.STAFF)
    Recording.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=400)
    )
    fresh = Recording.objects.create(
        daily_recording_id="fresh", status=Recording.Status.READY,
        content_visibility=Recording.Visibility.STAFF,
    )
    call_command("purge_old_recordings", "--dry-run")
    out = capsys.readouterr().out
    assert old.daily_recording_id in out or "would delete" in out
    # dry-run changed nothing
    assert Recording.objects.get(pk=old.pk).status == Recording.Status.READY
    assert Recording.objects.filter(pk=fresh.pk).exists()
