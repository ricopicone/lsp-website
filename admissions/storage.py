"""Private storage for applicant CVs.

A CV is a personal document, so its bytes must never be reachable by a bare,
permanent media URL (the project's default storage is the *public* S3 bucket).
CVs are stored in the access-controlled location (a private S3 bucket in
production, or a local ``private-media`` dir in dev — see :mod:`core.storage`)
and served only through the access-checked download view
(:func:`admissions.views.cv_download`). The storage refuses to build a URL so a
stray ``{{ application.cv.url }}`` fails loudly rather than leaking access.
"""

from __future__ import annotations

from django.conf import settings
from django.core.files.storage import FileSystemStorage

_URL_ERROR = (
    "Applicant CVs are private; serve them via the admissions:cv_download "
    "view, not a media URL."
)


class PrivateCVStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(location=settings.ADMISSIONS_UPLOADS_ROOT)

    def url(self, name):
        raise ValueError(_URL_ERROR)


def cv_storage():
    """Private S3 in production (``AWS_PRIVATE_STORAGE_BUCKET_NAME`` set), else a
    local private-media filesystem store. Both refuse to build a URL."""
    bucket = getattr(settings, "AWS_PRIVATE_STORAGE_BUCKET_NAME", "")
    if bucket:
        from storages.backends.s3 import S3Storage

        class _PrivateS3CVStorage(S3Storage):
            def url(self, name, parameters=None, expire=None, http_method=None):
                raise ValueError(_URL_ERROR)

        return _PrivateS3CVStorage(
            bucket_name=bucket,
            region_name=getattr(settings, "AWS_S3_REGION_NAME", "us-west-2"),
            location="admissions",   # namespace within the private bucket
            querystring_auth=True,
            default_acl=None,
            file_overwrite=False,
        )
    return PrivateCVStorage()
