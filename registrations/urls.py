from django.urls import path

from . import views, views_admin

app_name = "registrations"

#: The Registration Admin console (task #470) lives with the other
#: admin-tools surfaces.
_ADMIN = "admin-tools/registrations"

urlpatterns = [
    path(f"{_ADMIN}/", views_admin.registrar_registrations, name="registrar"),
    path(f"{_ADMIN}/help/", views_admin.registrar_help, name="registrar_help"),
    path(f"{_ADMIN}/export.csv", views_admin.registrar_registrations_csv,
         name="registrar_csv"),
    path(f"{_ADMIN}/events/", views_admin.registrar_events,
         name="registrar_events"),
    path(f"{_ADMIN}/events/<int:pk>/toggle/", views_admin.registrar_event_toggle,
         name="registrar_event_toggle"),
    path(f"{_ADMIN}/<int:reg_id>/approve/", views_admin.registrar_approve,
         name="registrar_approve"),
    path(f"{_ADMIN}/<int:reg_id>/decline/", views_admin.registrar_decline,
         name="registrar_decline"),
    path(f"{_ADMIN}/<int:reg_id>/comp/", views_admin.registrar_comp,
         name="registrar_comp"),
    path(f"{_ADMIN}/<int:reg_id>/note/", views_admin.registrar_note,
         name="registrar_note"),
    path(f"{_ADMIN}/<int:reg_id>/remove/", views_admin.registrar_remove,
         name="registrar_remove"),
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
        "registrations/<int:reg_id>/apply-code/",
        views.apply_code,
        name="apply_code",
    ),
    path(
        "registrations/installments/<int:installment_id>/pay/",
        views.pay_installment,
        name="pay_installment",
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
