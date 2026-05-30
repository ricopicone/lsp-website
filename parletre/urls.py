from django.urls import path

from . import views

app_name = "parletre"

urlpatterns = [
    path("", views.index, name="index"),
    path("notifications/", views.notifications, name="notifications"),
    path("mention-search/", views.mention_search, name="mention_search"),
    path("post/<int:post_id>/react/", views.react, name="react"),
    path("attachment/<int:attachment_id>/", views.attachment, name="attachment"),
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
