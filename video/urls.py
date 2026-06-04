from django.urls import path

from . import views

app_name = "video"

urlpatterns = [
    path("groups/<slug:slug>/room/", views.workgroup_room, name="workgroup_room"),
    path("events/<slug:slug>/room/", views.event_room, name="event_room"),
]
