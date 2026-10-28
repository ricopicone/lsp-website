"""A recording made outside the site's room can be uploaded to its event
(task #851, the Scholarly Seminar Series on Zoom).

An upload is an ordinary ``Recording`` with ``source=upload``, so it lists,
plays and is managed like one Daily made; what differs is where its file lives
(the private bucket) and that Daily is never asked about it. The conftest makes
any Daily call here fail loudly.
"""
from __future__ import annotations

import datetime as dt

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from video import uploads
from video.models import Recording

from .factories import special_event, user

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _local_private_media(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = str(tmp_path)


def _video(name="talk.mp4", size=64):
    return SimpleUploadedFile(name, b"\0" * size, content_type="video/mp4")


def _attach(event, **extra):
    key = uploads.store_file(event, _video())
    return uploads.attach(
        event, key=key, by=extra.pop("by", None),
        recorded_on=extra.pop("recorded_on", event.start_date),
        visibility=extra.pop("visibility", Recording.Visibility.MEMBERS),
    )


def test_an_upload_is_a_ready_recording_on_its_event():
    event = special_event(slug="zoom-talk")
    uploader = user("coord@x.test")
    rec = _attach(event, by=uploader, recorded_on=dt.date(2026, 11, 7))
    assert rec.source == Recording.Source.UPLOAD
    assert rec.status == Recording.Status.READY
    assert rec.event == event and rec.started_by == uploader
    assert rec.daily_recording_id is None
    assert rec.s3_key.startswith(f"recordings/uploads/{event.pk}/")
    assert timezone.localtime(rec.started_at).date() == dt.date(2026, 11, 7)
    # One-off events' recordings are exempt from retention, as Daily's are.
    assert rec.keep


def test_who_can_watch_is_set_at_upload():
    rec = _attach(special_event(slug="public-talk"),
                  visibility=Recording.Visibility.PUBLIC)
    assert rec.listing_visibility == rec.content_visibility == Recording.Visibility.PUBLIC


def test_two_uploads_need_no_daily_id():
    event = special_event(slug="two")
    _attach(event)
    _attach(event)
    assert Recording.objects.filter(event=event).count() == 2


def test_an_upload_plays_from_the_site_not_from_daily(client):
    rec = _attach(special_event(slug="plays"))
    url = rec.playable_url()
    assert url  # dev: the site streams the stored file
    client.force_login(user("member@x.test"))
    assert client.get(url).status_code == 200


def test_the_stored_file_obeys_who_can_watch(client):
    rec = _attach(special_event(slug="gated"), visibility=Recording.Visibility.OWNERS)
    client.force_login(user("member@x.test"))
    assert client.get(rec.playable_url()).status_code == 403


def test_deleting_an_upload_removes_its_file_and_never_calls_daily():
    from core.storage import private_storage

    rec = _attach(special_event(slug="gone"))
    key = rec.s3_key
    assert private_storage().exists(key)
    rec.delete_everywhere()  # the conftest fails any Daily call
    assert not private_storage().exists(key)
    assert not Recording.objects.filter(pk=rec.pk).exists()


def test_the_retention_purge_never_sends_an_upload_to_daily():
    from django.core.management import call_command

    rec = _attach(special_event(slug="old"))
    Recording.objects.filter(pk=rec.pk).update(
        keep=False, created_at=timezone.now() - dt.timedelta(days=800),
    )
    call_command("purge_old_recordings")
    rec.refresh_from_db()
    assert rec.status == Recording.Status.DELETED


# --- Validating what was uploaded --------------------------------------------

def test_only_video_files_are_accepted():
    with pytest.raises(uploads.UploadError):
        uploads.store_file(special_event(slug="pdf"), SimpleUploadedFile(
            "notes.pdf", b"x", content_type="application/pdf"))


def test_a_direct_upload_must_be_this_events(monkeypatch):
    import core.storage as storage

    monkeypatch.setattr(storage, "head_private_object",
                        lambda key: {"size": 10, "content_type": "video/mp4"})
    mine, other = special_event(slug="mine"), special_event(slug="other")
    good = f"recordings/uploads/{mine.pk}/abc.mp4"
    assert uploads.verify_key(mine, good) == good
    for bad in (f"recordings/uploads/{other.pk}/abc.mp4", "works/videos/x.mp4",
                f"recordings/uploads/{mine.pk}/../{other.pk}/abc.mp4"):
        with pytest.raises(uploads.UploadError):
            uploads.verify_key(mine, bad)


def test_a_direct_upload_that_never_arrived_is_refused(monkeypatch):
    import core.storage as storage

    monkeypatch.setattr(storage, "head_private_object", lambda key: None)
    event = special_event(slug="missing")
    with pytest.raises(uploads.UploadError):
        uploads.verify_key(event, f"recordings/uploads/{event.pk}/abc.mp4")


def test_presign_names_a_key_under_the_event(monkeypatch):
    import core.storage as storage

    seen = {}

    def _post(key, *, max_bytes, content_type):
        seen.update(key=key, max_bytes=max_bytes)
        return {"url": "https://s3.example/", "fields": {"key": key}}

    monkeypatch.setattr(storage, "presigned_upload_post", _post)
    event = special_event(slug="presign")
    ticket = uploads.presign(event, "Talk Recording.MP4", "video/mp4")
    assert ticket["key"] == seen["key"]
    assert seen["key"].startswith(f"recordings/uploads/{event.pk}/")
    assert seen["key"].endswith(".mp4")
    assert seen["max_bytes"] == uploads.MAX_BYTES


def test_presign_without_a_bucket_says_to_post_the_file():
    assert uploads.presign(special_event(slug="dev"), "t.mp4", "video/mp4") is None
