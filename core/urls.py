from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("calendar/", views.calendar_page, name="calendar"),
    path("calendar/events.json", views.calendar_events_json, name="calendar_events"),
]
