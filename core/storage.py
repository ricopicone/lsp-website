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


def _presigned_get(bucket, key, *, download=False, expires=21600, default_name="file"):
    """A signed, time-limited GET URL for ``key`` in ``bucket``.

    Generated directly via boto3 with **SigV4** (Storage.url() defaults to the
    deprecated SigV2 here, and video playback needs reliable range requests). The
    URL is valid until ``expires`` or the signing instance-role credentials lapse,
    whichever is sooner (~6h). ``download`` forces a Content-Disposition attachment.
    """
    if not bucket or not key:
        return None
    import boto3
    from botocore.config import Config

    region = getattr(settings, "AWS_S3_REGION_NAME", "us-west-2")
    params = {"Bucket": bucket, "Key": key}
    if download:
        fname = key.rsplit("/", 1)[-1] or default_name
        params["ResponseContentDisposition"] = f'attachment; filename="{fname}"'
    client = boto3.client(
        "s3",
        region_name=region,
        # Pin the REGIONAL endpoint: the global s3.amazonaws.com host with a
        # SigV4 signature scoped to us-west-2 is rejected (403); the regional
        # endpoint validates correctly.
        endpoint_url=f"https://s3.{region}.amazonaws.com",
        config=Config(signature_version="s3v4"),
    )
    return client.generate_presigned_url("get_object", Params=params, ExpiresIn=expires)


def presigned_recordings_url(key, *, download=False, expires=21600):
    """A signed, range-capable GET URL for a recording object in our bucket."""
    bucket = getattr(settings, "AWS_RECORDINGS_BUCKET_NAME", "") or getattr(
        settings, "AWS_PRIVATE_STORAGE_BUCKET_NAME", ""
    )
    return _presigned_get(bucket, key, download=download, expires=expires,
                          default_name="recording.mp4")


def presigned_private_url(key, *, download=False, expires=21600):
    """A signed, range-capable GET URL for an object in the private bucket
    (gated Work/Document content — e.g. a Work's streamed video). Returns None
    in local/dev where there is no private bucket (callers fall back to the
    storage URL)."""
    bucket = getattr(settings, "AWS_PRIVATE_STORAGE_BUCKET_NAME", "")
    return _presigned_get(bucket, key, download=download, expires=expires,
                          default_name="video.mp4")


def _private_bucket() -> str:
    return getattr(settings, "AWS_PRIVATE_STORAGE_BUCKET_NAME", "")


def _s3_client():
    import boto3
    from botocore.config import Config

    region = getattr(settings, "AWS_S3_REGION_NAME", "us-west-2")
    return boto3.client(
        "s3", region_name=region,
        endpoint_url=f"https://s3.{region}.amazonaws.com",
        config=Config(signature_version="s3v4"),
    )


def presigned_upload_post(key, *, max_bytes, content_type, expires=3600):
    """A presigned **POST** for a browser to upload one object directly to the
    private bucket. POST (not PUT) so S3 itself enforces the size cap via a
    ``content-length-range`` condition and a fixed key + content-type. Returns
    a dict ``{url, fields}`` for an HTML/JS multipart POST, or None when there
    is no private bucket (dev: callers fall back to a server-side upload)."""
    bucket = _private_bucket()
    if not bucket or not key:
        return None
    conditions = [
        {"key": key},
        {"Content-Type": content_type},
        ["content-length-range", 1, int(max_bytes)],
    ]
    return _s3_client().generate_presigned_post(
        Bucket=bucket, Key=key,
        Fields={"Content-Type": content_type},
        Conditions=conditions,
        ExpiresIn=expires,
    )


def head_private_object(key):
    """``{size, content_type}`` for an object in the private bucket, or None if
    it's missing/unreadable. Used to verify a direct upload before attaching."""
    bucket = _private_bucket()
    if not bucket or not key:
        return None
    try:
        resp = _s3_client().head_object(Bucket=bucket, Key=key)
    except Exception:
        return None
    return {"size": resp.get("ContentLength", 0),
            "content_type": resp.get("ContentType", "")}


def copy_private_object(src_key, dest_key) -> bool:
    """Server-side copy within the private bucket (no app bandwidth — S3 does
    it internally). Used to promote a verified upload out of the temporary
    ``incoming/`` prefix into its permanent home. Returns success."""
    bucket = _private_bucket()
    if not bucket or not src_key or not dest_key:
        return False
    try:
        _s3_client().copy_object(
            Bucket=bucket, Key=dest_key,
            CopySource={"Bucket": bucket, "Key": src_key},
        )
    except Exception:
        return False
    return True


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
