"""Storage for access-controlled uploads.

Gated content — members-only / group-only Work and Document PDFs, workgroup
working-document files, and Parlêtre attachments — must never be reachable by a
bare, permanent public URL. It lives in a **private** S3 bucket in production
(objects are not public-read; access is granted only by the app's access-checked
download views, which stream the bytes server-side) or a local ``private-media``
directory in development.

This is distinct from the *public* ``default`` storage (headshots, cover images,
speaker photos) configured in ``production.py``, whose bucket is public-read.

The field references ``private_storage`` as a *callable*, so migrations record
its import path rather than a frozen instance — keeping them portable across
environments (S3 in prod, filesystem locally).
"""

from __future__ import annotations

from django.conf import settings
from django.core.files.storage import FileSystemStorage


def private_storage():
    """Return the storage backend for access-controlled uploads.

    Private S3 (signed, expiring URLs — never public) when
    ``AWS_PRIVATE_STORAGE_BUCKET_NAME`` is set; otherwise a local filesystem
    store under ``PRIVATE_MEDIA_ROOT``, outside the public ``MEDIA_ROOT``.
    """
    bucket = getattr(settings, "AWS_PRIVATE_STORAGE_BUCKET_NAME", "")
    if bucket:
        from storages.backends.s3 import S3Storage

        return S3Storage(
            bucket_name=bucket,
            region_name=getattr(settings, "AWS_S3_REGION_NAME", "us-west-2"),
            querystring_auth=True,   # signed, time-limited URLs; never public
            default_acl=None,        # bucket blocks public access
            file_overwrite=False,
        )
    return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT)


def recordings_storage():
    """Storage for owned video recordings (Daily writes the mp4 here when
    ``recordings_bucket`` is configured). Signed, expiring URLs — never public.
    Falls back to the private bucket / local store when no dedicated bucket is set."""
    bucket = getattr(settings, "AWS_RECORDINGS_BUCKET_NAME", "") or getattr(
        settings, "AWS_PRIVATE_STORAGE_BUCKET_NAME", ""
    )
    if bucket:
        from storages.backends.s3 import S3Storage

        return S3Storage(
            bucket_name=bucket,
            region_name=getattr(settings, "AWS_S3_REGION_NAME", "us-west-2"),
            querystring_auth=True,
            default_acl=None,
            file_overwrite=False,
        )
    return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT)
