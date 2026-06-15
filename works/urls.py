from django.urls import path

from . import views

app_name = "works"

urlpatterns = [
    path("", views.index, name="index"),
    path("add/", views.add, name="add"),
    path("mine/", views.my_works, name="mine"),
    path("<slug:slug>/", views.detail, name="detail"),
    path("<slug:slug>/edit/", views.edit, name="edit"),
    path("<slug:slug>/delete/", views.delete, name="delete"),
    path("<slug:slug>/pdf/<int:file_id>/", views.download, name="download"),
    path("<slug:slug>/video/", views.video, name="video"),
    path("video/presign/", views.video_presign, name="video_presign"),
]
