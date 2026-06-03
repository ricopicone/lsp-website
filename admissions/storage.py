"""Private storage for applicant CVs.

A CV is a personal document, so its bytes must never be reachable by a bare
media URL (the project's default storage is the *public* S3 bucket). CVs are
stored outside any web-served root and served only through the access-checked
download view (:func:`admissions.views.cv_download`). Mirrors
``parletre.storage`` — swap for a private-ACL S3 backend when one exists; the
download view is unaffected because it never builds a public URL.
"""

from __future__ import annotations

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateCVStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(location=settings.ADMISSIONS_UPLOADS_ROOT)

    def url(self, name):
        raise ValueError(
            "Applicant CVs are private; serve them via the admissions:cv_download "
            "view, not a media URL."
        )


def cv_storage() -> PrivateCVStorage:
    return PrivateCVStorage()
