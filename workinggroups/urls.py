from django.urls import path

from . import views

app_name = "workinggroups"

urlpatterns = [
    path("new/", views.create, name="create"),
]
