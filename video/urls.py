from django.urls import path

from . import views

app_name = "video"

urlpatterns = [
    path("video/system-check/", views.system_check, name="system_check"),
    path("video/recordings/<int:pk>/", views.recording_play, name="recording_play"),
    path("video/webhooks/daily/", views.recording_webhook, name="recording_webhook"),
    path("groups/<slug:slug>/room/", views.workgroup_room, name="workgroup_room"),
    path("events/<slug:slug>/room/", views.event_room, name="event_room"),
]
