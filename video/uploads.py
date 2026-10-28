"""Recordings made outside the site's room, uploaded to their event (task #851).

The Scholarly Seminar Series sometimes meets on Zoom, where the site can't
record. Its coordinator uploads the recording instead, and it becomes an
ordinary ``Recording`` (``source=upload``) on the talk: listed, played and
managed exactly like one Daily made. Design:
docs/superpowers/specs/2026-10-27-recording-upload-design.md.

The file lives in the private bucket, which browsers already upload video to
(Works, ``core.storage.presigned_upload_post``), under a prefix naming the
event. The browser uploads straight to S3 and only the key comes back to the
site; without a bucket (development) or JavaScript the file posts to the site.
"""
from __future__ import annotations

import datetime as dt
import os
import uuid

from django.utils import timezone

UPLOAD_PREFIX = "recordings/uploads/"
VIDEO_EXTS = (".mp4", ".webm", ".mov", ".m4v")
#: About four hours of Zoom's 720p recording; S3's limit for one POST is 5 GB.
MAX_BYTES = 4 * 1024 ** 3
MAX_LABEL = "4 GB"


class UploadError(ValueError):
    """A member-facing reason an upload can't be used."""


def prefix_for(event) -> str:
    return f"{UPLOAD_PREFIX}{event.pk}/"


def check_filename(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in VIDEO_EXTS:
        raise UploadError("Please choose an MP4, WebM or MOV file.")
    return ext


def _new_key(event, filename: str) -> str:
    return f"{prefix_for(event)}{uuid.uuid4().hex}{check_filename(filename)}"


def presign(event, filename: str, content_type: str) -> dict | None:
    """A one-time ticket for the browser to upload straight to S3: ``{key, url,
    fields}``. None when there is no private bucket, so the form posts the file
    to the site instead. S3 enforces the size cap and the key."""
    from core import storage

    if not (content_type or "").startswith("video/"):
        raise UploadError("Please choose an MP4, WebM or MOV file.")
    key = _new_key(event, filename)
    post = storage.presigned_upload_post(
        key, max_bytes=MAX_BYTES, content_type=content_type,
    )
    if post is None:
        return None
    return {"key": key, "url": post["url"], "fields": post["fields"]}


def verify_key(event, key: str) -> str:
    """Check a direct upload before trusting it: under this event's prefix (so
    no one can attach another event's file, or any other object), and actually
    in the bucket within the cap."""
    from core import storage

    key = (key or "").strip()
    rest = key[len(prefix_for(event)):]
    if not key.startswith(prefix_for(event)) or not rest or "/" in rest:
        raise UploadError("That upload doesn't belong to this talk. Please try again.")
    check_filename(rest)
    head = storage.head_private_object(key)
    if head is None:
        raise UploadError("That upload didn't finish. Please try again.")
    if head["size"] > MAX_BYTES:
        raise UploadError(f"That file is over the {MAX_LABEL} limit.")
    return key


def store_file(event, upload) -> str:
    """Save a file posted to the site itself (no bucket, or no JavaScript);
    returns its key."""
    from core.storage import private_storage

    key = _new_key(event, upload.name)
    if upload.size > MAX_BYTES:
        raise UploadError(f"That file is over the {MAX_LABEL} limit.")
    return private_storage().save(key, upload)


def attach(event, *, key: str, by, recorded_on: dt.date, visibility: str):
    """Make the uploaded file a ready recording on ``event``.

    Both availability settings take the one choice made at upload; the
    recording's page splits them later if wanted. Kept from the retention
    sweep on the rule ingest applies to a one-off event's recording."""
    from events.models import Event

    from .models import Recording

    # Noon on the day, in the school's timezone, so no reading of it lands on
    # the day before or after.
    started_at = timezone.make_aware(dt.datetime.combine(recorded_on, dt.time(12)))
    return Recording.objects.create(
        source=Recording.Source.UPLOAD,
        event=event,
        started_by=by,
        s3_key=key,
        status=Recording.Status.READY,
        started_at=started_at,
        title=f"{event.title} — {recorded_on.isoformat()}",
        listing_visibility=visibility,
        content_visibility=visibility,
        keep=event.event_type not in Event.ANNUAL_PROGRAM_TYPES,
    )
