"""Referral workflow URLs.

Mounted at the project root: coordinator pages live under
``/admin-tools/referrals/`` (alongside the other admin-tools surfaces) and
the clinician respond page under ``/referrals/<reference>/respond/``.
"""

from django.urls import path

from . import views

app_name = "referrals"

_ADMIN = "admin-tools/referrals"

urlpatterns = [
    path(f"{_ADMIN}/", views.dashboard, name="dashboard"),
    path(f"{_ADMIN}/settings/", views.settings_view, name="settings"),
    path(f"{_ADMIN}/templates/", views.templates_list, name="templates"),
    path(f"{_ADMIN}/templates/<str:key>/", views.template_edit,
         name="template_edit"),
    path(f"{_ADMIN}/clinicians/", views.clinicians, name="clinicians"),
    path(f"{_ADMIN}/clinicians/<int:pk>/edit/", views.clinician_edit,
         name="clinician_edit"),
    path(f"{_ADMIN}/clinicians/<int:pk>/toggle/", views.clinician_toggle,
         name="clinician_toggle"),
    path(f"{_ADMIN}/clinicians/<int:pk>/onboard/", views.clinician_onboard,
         name="clinician_onboard"),
    path(f"{_ADMIN}/<str:reference>/", views.detail, name="detail"),
    path(f"{_ADMIN}/<str:reference>/ack/", views.send_ack, name="send_ack"),
    path(f"{_ADMIN}/<str:reference>/distribute/", views.distribute,
         name="distribute"),
    path(f"{_ADMIN}/<str:reference>/record-response/", views.record_response,
         name="record_response"),
    path(f"{_ADMIN}/<str:reference>/followup/", views.followup,
         name="followup"),
    path(f"{_ADMIN}/<str:reference>/close/", views.close, name="close"),
    path(f"{_ADMIN}/<str:reference>/reopen/", views.reopen, name="reopen"),
    path(f"{_ADMIN}/<str:reference>/notes/", views.save_notes, name="notes"),
    # Clinician-facing (step 4).
    path("referrals/<str:reference>/respond/", views.respond, name="respond"),
]
