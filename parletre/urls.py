from django.urls import path

from . import views

app_name = "parletre"

urlpatterns = [
    path("", views.index, name="index"),
    path("heartbeat/", views.heartbeat, name="heartbeat"),
    path("notifications/", views.notifications, name="notifications"),
    path("settings/", views.preferences, name="settings"),
    path("search/", views.search, name="search"),
    path("mention-search/", views.mention_search, name="mention_search"),
    path("member-search/", views.member_search, name="member_search"),
    path("new-chat/", views.create_private_chat, name="create_private_chat"),
    path("inbound/", views.inbound, name="inbound"),
    path("post/<int:post_id>/react/", views.react, name="react"),
    path("post/<int:post_id>/edit/", views.edit_post, name="edit_post"),
    path("post/<int:post_id>/delete/", views.delete_post, name="delete_post"),
    path("attachment/<int:attachment_id>/", views.attachment, name="attachment"),
    path("<slug:slug>/", views.channel, name="channel"),
    path("<slug:slug>/subscribe/", views.subscribe, name="subscribe"),
    path("<slug:slug>/participants/", views.manage_participants, name="manage_participants"),
    path("<slug:slug>/leave/", views.leave_chat, name="leave_chat"),
    path("<slug:slug>/delete/", views.delete_chat, name="delete_chat"),
    path("<slug:slug>/new/", views.new_thread, name="new_thread"),
    path("<slug:slug>/<slug:thread_slug>/", views.thread, name="thread"),
    path(
        "<slug:slug>/<slug:thread_slug>/moderate/",
        views.moderate_thread,
        name="moderate_thread",
    ),
]
