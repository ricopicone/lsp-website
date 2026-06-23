"""Analyst-availability console URLs.

Mounted at the project root; the console lives under
``/admin-tools/availability/`` alongside the other admin-tools surfaces.
"""

from django.urls import path

from . import views

app_name = "availability"

_ADMIN = "admin-tools/availability"

urlpatterns = [
    path(f"{_ADMIN}/", views.grid, name="grid"),
    path(f"{_ADMIN}/overview/", views.overview, name="overview"),
    path(f"{_ADMIN}/settings/", views.settings_view, name="settings"),
    path(f"{_ADMIN}/reminders/send/", views.send_reminders, name="send_reminders"),
    path(f"{_ADMIN}/message/", views.template_edit, name="templates"),
    path(f"{_ADMIN}/analyst/<int:pk>/", views.analyst, name="analyst"),
    # Member self-service (from the profile editor).
    path("accounts/availability/", views.self_update, name="self_update"),
]
