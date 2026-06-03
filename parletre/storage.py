"""Private storage for Parlêtre attachments.

Attachments may live in private channels, so their bytes must never be
reachable by a bare, permanent media URL — only through the access-checked
download view (:func:`parletre.views.attachment`). They are therefore stored in
the access-controlled location (a private S3 bucket in production, or a local
``private-media`` dir in dev — see :mod:`core.storage`), and this storage's
``url()`` refuses to build a link so a stray ``{{ attachment.file.url }}`` fails
loudly rather than leaking a public URL.

The field references this as a *callable* (``storage=attachment_storage``), so
migrations record its import path, not a frozen storage instance — keeping the
migration portable across environments.
"""

from __future__ import annotations

from django.conf import settings
from django.core.files.storage import FileSystemStorage

_URL_ERROR = (
    "Parlêtre attachments are private; serve them via the "
    "parletre:attachment download view, not a media URL."
)


class PrivateAttachmentStorage(FileSystemStorage):
    """Local filesystem store under a non-public root that refuses URLs."""

    def __init__(self):
        super().__init__(location=settings.PARLETRE_ATTACHMENTS_ROOT)

    def url(self, name):
        raise ValueError(_URL_ERROR)


def attachment_storage():
    """Private S3 in production (``AWS_PRIVATE_STORAGE_BUCKET_NAME`` set),
    else a local private-media filesystem store. Both refuse to build a URL —
    attachments are reachable only through the access-checked download view."""
    bucket = getattr(settings, "AWS_PRIVATE_STORAGE_BUCKET_NAME", "")
    if bucket:
        from storages.backends.s3 import S3Storage

        class _PrivateS3AttachmentStorage(S3Storage):
            def url(self, name, parameters=None, expire=None, http_method=None):
                raise ValueError(_URL_ERROR)

        return _PrivateS3AttachmentStorage(
            bucket_name=bucket,
            region_name=getattr(settings, "AWS_S3_REGION_NAME", "us-west-2"),
            location="parletre",     # namespace within the private bucket
            querystring_auth=True,
            default_acl=None,
            file_overwrite=False,
        )
    return PrivateAttachmentStorage()
