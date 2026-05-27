from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("<slug:slug>/", views.event_detail, name="detail"),
]
