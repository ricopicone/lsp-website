from django.urls import path

from . import views

app_name = "parletre"

urlpatterns = [
    path("", views.index, name="index"),
    path("notifications/", views.notifications, name="notifications"),
    path("post/<int:post_id>/react/", views.react, name="react"),
    path("<slug:slug>/", views.channel, name="channel"),
    path("<slug:slug>/subscribe/", views.subscribe, name="subscribe"),
    path("<slug:slug>/new/", views.new_thread, name="new_thread"),
    path("<slug:slug>/<slug:thread_slug>/", views.thread, name="thread"),
    path(
        "<slug:slug>/<slug:thread_slug>/moderate/",
        views.moderate_thread,
        name="moderate_thread",
    ),
]
