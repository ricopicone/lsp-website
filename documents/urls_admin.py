"""Management routes for documents.

``documents.urls`` is mounted at ``documents/`` and so cannot host an
``admin-tools/`` path; this module is included at the root instead, the way
``admissions.urls`` owns its own ``admin-tools/web-coordinator/admit/`` route.
"""

from django.urls import path

from . import views_admin

app_name = "documents_admin"

_PREFIX = "admin-tools/web-coordinator/documents/"

urlpatterns = [
    path(_PREFIX, views_admin.index, name="index"),
    path(f"{_PREFIX}<slug:slug>/", views_admin.edit, name="edit"),
    path(f"{_PREFIX}<slug:slug>/revisions/<int:pk>/download/",
         views_admin.revision_download, name="revision_download"),
    path(f"{_PREFIX}<slug:slug>/revisions/<int:pk>/restore/",
         views_admin.restore, name="restore"),
]
