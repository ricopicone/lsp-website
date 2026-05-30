from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("", views.index, name="index"),
    path("<slug:slug>/", views.detail, name="detail"),
    path("<slug:slug>/download/", views.download, name="download"),
]
