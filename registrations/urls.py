from django.urls import path

from . import views

app_name = "registrations"

urlpatterns = [
    path(
        "events/<slug:event_slug>/register/",
        views.register_for_event,
        name="register",
    ),
    path(
        "registrations/<int:reg_id>/confirmation/",
        views.registration_confirm,
        name="confirm",
    ),
    path(
        "registrations/<int:reg_id>/cancel/",
        views.cancel_registration,
        name="cancel",
    ),
    path(
        "registrations/<int:reg_id>/pay/",
        views.pay_registration,
        name="pay",
    ),
    path(
        "registrations/<int:reg_id>/approve/",
        views.approve_registration,
        name="approve",
    ),
    path(
        "registrations/<int:reg_id>/decline/",
        views.decline_registration,
        name="decline",
    ),
]
