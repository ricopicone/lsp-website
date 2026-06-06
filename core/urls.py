from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("walkthrough/", views.set_walkthrough, name="set_walkthrough"),
    path("calendar/", views.calendar_page, name="calendar"),
    path("calendar/events.json", views.calendar_events_json, name="calendar_events"),
    path("impersonate/", views.impersonate_picker, name="impersonate_picker"),
    path("impersonate/stop/", views.impersonate_stop, name="impersonate_stop"),
    path("impersonate/<int:user_id>/", views.impersonate_start, name="impersonate_start"),
]
