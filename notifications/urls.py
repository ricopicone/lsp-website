from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.feed, name="feed"),
    path("settings/", views.settings_page, name="settings"),
    path("read-all/", views.mark_all_read, name="mark_all_read"),
    path("<int:pk>/open/", views.open, name="open"),
]
