"""Private storage for Parlêtre attachments.

Attachments may live in private channels, so their bytes must never be
reachable by a bare media URL — only through the access-checked download
view (:func:`parletre.views.attachment`). They are therefore stored *outside*
the public ``MEDIA_ROOT`` (and outside the public S3 bucket), in a location
that no web server is configured to serve directly. ``base_url=None`` means
``FieldFile.url`` raises rather than silently producing a public link.

The field references this as a *callable* (``storage=attachment_storage``),
so migrations record its import path, not a frozen storage instance — keeping
the migration portable across environments.

When S3 is adopted for private content in a later milestone, swap this for a
private-ACL S3 backend; the download view and the rest of the app are
unaffected because they never build a public URL.
"""

from __future__ import annotations

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateAttachmentStorage(FileSystemStorage):
    """Filesystem storage under a non-public root that refuses to build URLs.

    (``FileSystemStorage(base_url=None)`` quietly falls back to ``MEDIA_URL``,
    so we override ``url`` to fail loudly — the only way to a Parlêtre
    attachment is the access-checked download view.)
    """

    def __init__(self):
        super().__init__(location=settings.PARLETRE_ATTACHMENTS_ROOT)

    def url(self, name):
        raise ValueError(
            "Parlêtre attachments are private; serve them via the "
            "parletre:attachment download view, not a media URL."
        )


def attachment_storage() -> PrivateAttachmentStorage:
    return PrivateAttachmentStorage()
