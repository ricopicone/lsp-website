from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("<slug:slug>/", views.event_detail, name="detail"),
    path("<slug:slug>/edit/", views.event_edit, name="edit"),
    path("<slug:slug>/codes/", views.event_generate_code, name="generate_code"),
    path("<slug:slug>/check-code/", views.check_pricing_code, name="check_code"),
]
