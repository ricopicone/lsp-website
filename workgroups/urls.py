from django.urls import path

from . import views

app_name = "workgroups"

urlpatterns = [
    path("", views.workgroup_list, name="list"),
    path("<slug:slug>/", views.workgroup_detail, name="detail"),
]
