from django.urls import path

from . import views

app_name = "committees"

urlpatterns = [
    path("<slug:slug>/charter/", views.edit_charter, name="edit_charter"),
]
