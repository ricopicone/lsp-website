"""Recording lifecycle: webhook ingestion, visibility, retention, deletion."""
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


# --- retention ---

def _ingest(event, room_name="lsp-event-keep", rec_id="rec-keep"):
    from video.services import ingest_recording_event

    DailyRoom.objects.create(
        event=event, name=room_name, url=f"https://x/{room_name}",
        provider_created=True,
    )
    return ingest_recording_event(
        "recording.ready-to-download",
        {"recording_id": rec_id, "room_name": room_name, "duration": 60},
    )


def test_special_event_recordings_are_kept_forever():
    # A special event is a one-off with an outside speaker; its recording is the
    # only record that the event happened. Never sweep it.
    from .factories import special_event

    rec = _ingest(special_event(slug="keep-special"))
    assert rec.keep is True


def test_one_off_event_recordings_are_kept_forever():
    # Days of Assembly, Working Days and Scholarly Seminars are equally
    # unrepeatable — the same reasoning applies.
    from events.models import Event

    from .factories import special_event

    for etype in (
        Event.Type.DAY_OF_ASSEMBLY,
        Event.Type.WORKING_DAY,
        Event.Type.SCHOLARLY_SEMINAR,
    ):
        e = special_event(slug=f"keep-{etype}")
        e.event_type = etype
        e.save(update_fields=["event_type"])
        rec = _ingest(e, room_name=f"lsp-event-{etype}", rec_id=f"rec-{etype}")
        assert rec.keep is True, etype


def test_recurring_offering_recordings_still_expire():
    # Seminars and reading groups run every year; their recordings stay on the
    # ordinary 1-year retention so storage doesn't grow without bound.
    wg = seminar(slug="keep-sem").ensure_workgroup()
    DailyRoom.objects.create(
        workgroup=wg, name="lsp-keep-sem", url="https://x/lsp-keep-sem",
        provider_created=True,
    )
    from video.services import ingest_recording_event

    rec = ingest_recording_event(
        "recording.ready-to-download",
        {"recording_id": "rec-sem", "room_name": "lsp-keep-sem", "duration": 60},
    )
    assert rec.keep is False


def test_purge_leaves_kept_recordings_alone():
    # The retention sweep must honour the flag, or "never delete" means nothing.
    from datetime import timedelta

    from django.core.management import call_command
    from django.utils import timezone

    from .factories import special_event

    rec = _ingest(special_event(slug="keep-purge"))
    assert rec.keep is True
    Recording.objects.filter(pk=rec.pk).update(
        created_at=timezone.now() - timedelta(days=800)
    )
    from io import StringIO

    out = StringIO()
    call_command("purge_old_recordings", "--dry-run", stdout=out)
    assert rec.daily_recording_id not in out.getvalue()
    rec.refresh_from_db()
    assert rec.status != Recording.Status.DELETED


# --- availability taxonomy (task #475) ---

V = Recording.Visibility


def _event_recording(event, *, content, listing=None):
    room = DailyRoom.objects.create(
        event=event, name=f"lsp-event-{event.slug}",
        url=f"https://x/{event.slug}", provider_created=True,
    )
    return Recording.objects.create(
        daily_recording_id=f"rv-{event.slug}", room=room, event=event,
        status=Recording.Status.READY,
        content_visibility=content, listing_visibility=listing or content,
    )


def test_registered_members_excludes_a_registered_non_member():
    # The distinction the whole taxonomy turns on: an external attendee who
    # registered is on the roster but is not an LSP member.
    from .factories import special_event

    ev = special_event(slug="avail-rm")
    rec = _event_recording(ev, content=V.ROSTER_MEMBERS)
    member = user("rm-member@x.test")          # factories give ANALYST
    register(member, ev)
    outsider = user("rm-outsider@x.test")
    outsider.profile.role = Profile.Role.EXTERNAL
    outsider.profile.save(update_fields=["role"])
    register(outsider, ev)
    assert rec.content_visible_to(member) is True
    assert rec.content_visible_to(outsider) is False


def test_registered_includes_a_registered_non_member():
    from .factories import special_event

    ev = special_event(slug="avail-roster")
    rec = _event_recording(ev, content=V.ROSTER)
    outsider = user("roster-outsider@x.test")
    outsider.profile.role = Profile.Role.EXTERNAL
    outsider.profile.save(update_fields=["role"])
    register(outsider, ev)
    assert rec.content_visible_to(outsider) is True


def test_members_level_ignores_registration():
    from .factories import special_event

    ev = special_event(slug="avail-members")
    rec = _event_recording(ev, content=V.MEMBERS)
    unregistered_member = user("m-unreg@x.test")
    assert rec.content_visible_to(unregistered_member) is True


def test_accounts_level_admits_any_signed_in_account():
    from .factories import special_event

    ev = special_event(slug="avail-accounts")
    rec = _event_recording(ev, content=V.ACCOUNTS)
    auditor = user("auditor@x.test")
    auditor.profile.role = Profile.Role.EXTERNAL
    auditor.profile.save(update_fields=["role"])
    assert rec.content_visible_to(auditor) is True


def test_owners_level_admits_only_owners():
    from .factories import special_event

    ev = special_event(slug="avail-owners")
    rec = _event_recording(ev, content=V.OWNERS)
    speaker = user("owners-speaker@x.test")
    ev.member_speakers.add(speaker)
    attendee = user("owners-att@x.test")
    register(attendee, ev)
    assert rec.content_visible_to(speaker) is True
    assert rec.content_visible_to(attendee) is False


def test_a_non_member_host_can_watch_their_own_members_only_recording():
    # The live bug this fixes: the MEMBERS level had no host fallback, so an
    # external speaker (role=external — Derek Hook's exact configuration) could
    # not watch the recording of his own talk.
    from .factories import special_event

    ev = special_event(slug="avail-hostgap")
    rec = _event_recording(ev, content=V.MEMBERS)
    guest = user("guest-speaker@x.test")
    guest.profile.role = Profile.Role.EXTERNAL
    guest.profile.save(update_fields=["role"])
    ev.member_speakers.add(guest)
    assert rec.content_visible_to(guest) is True


def test_web_roles_can_manage_any_recording():
    from core.models import StaffRole

    from .factories import special_event

    ev = special_event(slug="avail-webrole")
    rec = _event_recording(ev, content=V.OWNERS)
    wc = user("wc-rec@x.test")
    role, _ = StaffRole.objects.get_or_create(
        key=StaffRole.WEB_COORDINATOR, defaults={"name": "Web Coordinator"}
    )
    role.holders.add(wc)
    assert rec.can_manage(wc) is True
    assert rec.content_visible_to(wc) is True


def test_containment_rejects_the_incomparable_pair():
    # "Registered" and "LSP Members" are incomparable: neither contains the
    # other, so this combination has no coherent meaning and must be refused.
    from django.core.exceptions import ValidationError

    from .factories import special_event

    ev = special_event(slug="avail-incomp")
    rec = _event_recording(ev, content=V.ROSTER, listing=V.MEMBERS)
    with pytest.raises(ValidationError):
        rec.full_clean(exclude=["daily_recording_id"])


def test_containment_allows_a_genuine_narrowing():
    from .factories import special_event

    ev = special_event(slug="avail-ok")
    rec = _event_recording(ev, content=V.ROSTER_MEMBERS, listing=V.MEMBERS)
    rec.full_clean(exclude=["daily_recording_id"])  # must not raise


def test_containment_still_rejects_content_wider_than_listing():
    from django.core.exceptions import ValidationError

    from .factories import special_event

    ev = special_event(slug="avail-wider")
    rec = _event_recording(ev, content=V.PUBLIC, listing=V.MEMBERS)
    with pytest.raises(ValidationError):
        rec.full_clean(exclude=["daily_recording_id"])


def test_host_can_set_availability_from_the_recording_page(client):
    from .factories import special_event

    ev = special_event(slug="avail-setform")
    rec = _event_recording(ev, content=V.OWNERS)
    host = user("set-host@x.test")
    ev.member_speakers.add(host)
    client.force_login(host)
    resp = client.post(
        reverse("video:recording_availability", args=[rec.pk]),
        {"listing_visibility": V.MEMBERS, "content_visibility": V.ROSTER_MEMBERS},
    )
    assert resp.status_code == 302
    rec.refresh_from_db()
    assert rec.listing_visibility == V.MEMBERS
    assert rec.content_visibility == V.ROSTER_MEMBERS


def test_availability_form_refuses_an_incomparable_pair(client):
    from .factories import special_event

    ev = special_event(slug="avail-setbad")
    rec = _event_recording(ev, content=V.OWNERS)
    host = user("bad-host@x.test")
    ev.member_speakers.add(host)
    client.force_login(host)
    resp = client.post(
        reverse("video:recording_availability", args=[rec.pk]),
        {"listing_visibility": V.MEMBERS, "content_visibility": V.ROSTER},
    )
    rec.refresh_from_db()
    assert rec.content_visibility == V.OWNERS  # unchanged
    assert resp.status_code in (200, 302)


def test_non_host_cannot_set_availability(client):
    from .factories import special_event

    ev = special_event(slug="avail-setdenied")
    rec = _event_recording(ev, content=V.OWNERS)
    attendee = user("set-att@x.test")
    register(attendee, ev)
    client.force_login(attendee)
    resp = client.post(
        reverse("video:recording_availability", args=[rec.pk]),
        {"listing_visibility": V.PUBLIC, "content_visibility": V.PUBLIC},
    )
    assert resp.status_code == 403
    rec.refresh_from_db()
    assert rec.content_visibility == V.OWNERS


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


def test_visibility_roster_only():
    # "Registered group members": for an offering this resolves to the current
    # term's paid/comped registrants, so a member who never registered is out.
    event = seminar()
    wg = event.ensure_workgroup()
    rec = _recording(wg, content=Recording.Visibility.ROSTER)
    paid = user("p@x.test")
    register(paid, event)  # PAID
    member = user("m2@x.test")  # member, not registered
    assert rec.content_visible_to(paid) is True
    assert rec.content_visible_to(member) is False


def test_visibility_owners_only_needs_host():
    event = seminar()
    wg = event.ensure_workgroup()
    rec = _recording(wg, content=Recording.Visibility.OWNERS)
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
    monkeypatch.setattr(Recording, "playable_url", lambda self, **kw: "https://x/play.mp4")
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


# --- keep toggle ---

def test_keep_toggle_host_only(client):
    event = seminar()
    wg = event.ensure_workgroup()
    rec = _recording(wg, content=Recording.Visibility.MEMBERS)
    member = user("k1@x.test")
    teacher = user("k2@x.test", is_faculty=True)
    event.add_faculty(teacher)
    url = reverse("video:recording_keep", args=[rec.pk])

    client.force_login(member)
    assert client.post(url).status_code == 403  # non-host can't manage
    assert Recording.objects.get(pk=rec.pk).keep is False

    client.force_login(teacher)
    assert client.post(url).status_code == 302  # host toggles
    assert Recording.objects.get(pk=rec.pk).keep is True
    client.post(url)
    assert Recording.objects.get(pk=rec.pk).keep is False  # toggles back


# --- annotate ---

def test_annotate_host_only(client):
    event = seminar()
    wg = event.ensure_workgroup()
    rec = _recording(wg, content=Recording.Visibility.MEMBERS)
    member = user("a1@x.test")
    teacher = user("a2@x.test", is_faculty=True)
    event.add_faculty(teacher)
    url = reverse("video:recording_annotate", args=[rec.pk])

    client.force_login(member)
    assert client.post(url, {"note": "nope"}).status_code == 403
    assert Recording.objects.get(pk=rec.pk).note == ""

    client.force_login(teacher)
    assert client.post(url, {"note": "Session 3 — masochism"}).status_code == 302
    assert Recording.objects.get(pk=rec.pk).note == "Session 3 — masochism"


# --- delete ---

def test_delete_host_only_removes_everywhere(client, monkeypatch):
    event = seminar()
    wg = event.ensure_workgroup()
    rec = _recording(wg, content=Recording.Visibility.MEMBERS)
    rec.s3_key = "k/rec-del.mp4"
    rec.daily_recording_id = "rec-del"
    rec.save(update_fields=["s3_key", "daily_recording_id"])
    member = user("d1@x.test")
    teacher = user("d2@x.test", is_faculty=True)
    event.add_faculty(teacher)
    url = reverse("video:recording_delete", args=[rec.pk])

    deleted = {"s3": [], "daily": []}
    monkeypatch.setattr(
        "core.storage.recordings_storage",
        lambda: type("S", (), {"delete": lambda self, k: deleted["s3"].append(k)})(),
    )
    monkeypatch.setattr("video.daily.delete_recording", lambda rid: deleted["daily"].append(rid))

    client.force_login(member)
    assert client.post(url).status_code == 403
    assert Recording.objects.filter(pk=rec.pk).exists()

    client.force_login(teacher)
    assert client.post(url).status_code == 302
    assert not Recording.objects.filter(pk=rec.pk).exists()
    assert deleted["s3"] == ["k/rec-del.mp4"]
    assert deleted["daily"] == ["rec-del"]


# --- retention ---

def test_purge_old_recordings_dry_run(capsys):
    from datetime import timedelta

    from django.core.management import call_command
    from django.utils import timezone

    wg = seminar().ensure_workgroup()
    old = _recording(wg, content=Recording.Visibility.OWNERS)
    Recording.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=400)
    )
    fresh = Recording.objects.create(
        daily_recording_id="fresh", status=Recording.Status.READY,
        content_visibility=Recording.Visibility.OWNERS,
    )
    call_command("purge_old_recordings", "--dry-run")
    out = capsys.readouterr().out
    assert old.daily_recording_id in out or "would delete" in out
    # dry-run changed nothing
    assert Recording.objects.get(pk=old.pk).status == Recording.Status.READY
    assert Recording.objects.filter(pk=fresh.pk).exists()
