from django.urls import path

from . import views, views_invitations, views_personal

app_name = "video"

urlpatterns = [
    path("video/system-check/", views.system_check, name="system_check"),
    path("video/recordings/<int:pk>/", views.recording_play, name="recording_play"),
    path("video/recordings/<int:pk>/keep/", views.recording_keep, name="recording_keep"),
    path("video/recordings/<int:pk>/note/", views.recording_annotate, name="recording_annotate"),
    path(
        "video/recordings/<int:pk>/availability/",
        views.recording_availability,
        name="recording_availability",
    ),
    path("video/recordings/<int:pk>/delete/", views.recording_delete, name="recording_delete"),
    path("video/webhooks/daily/", views.recording_webhook, name="recording_webhook"),
    # Private meeting rooms (task #687). The guest route is listed before the
    # member route so "g" can never be read as a room slug.
    path("video/my-room/", views_personal.my_room, name="my_room"),
    path("video/my-room/settings/", views_personal.room_settings, name="room_settings"),
    path("video/my-room/invite/", views_personal.room_invite, name="room_invite"),
    # Invitations into any room (task #694). Revoke is one endpoint for all
    # three targets; ``may_invite`` is what differs between them.
    path(
        "video/invitations/<int:pk>/revoke/",
        views_invitations.invitation_revoke, name="invitation_revoke",
    ),
    path(
        "video/invitations/<int:pk>/presence/",
        views_invitations.invitation_presence, name="invitation_presence",
    ),
    path(
        "meet/g/<slug:token>/presence/",
        views_invitations.guest_presence, name="guest_presence",
    ),
    path("meet/g/<slug:token>/", views_invitations.guest_room, name="guest_room"),
    path("meet/<slug:slug>/", views_personal.personal_room, name="personal_room"),
    path("meet/<slug:slug>/presence/", views_personal.room_presence, name="room_presence"),
    path("groups/<slug:slug>/room/", views.workgroup_room, name="workgroup_room"),
    path(
        "groups/<slug:slug>/room/invite/",
        views_invitations.workgroup_invite, name="workgroup_invite",
    ),
    path("events/<slug:slug>/room/", views.event_room, name="event_room"),
    path(
        "events/<slug:slug>/room/invite/",
        views_invitations.event_invite, name="event_invite",
    ),
]
