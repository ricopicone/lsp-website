from django.urls import path

from . import views

app_name = "cartels"

urlpatterns = [
    path("", views.index, name="index"),
]
