from django.urls import path

from . import analyst, coordinator, views
from . import direct_admit as direct_admit_views

app_name = "admissions"

# The Applications Coordinator's facilitation console.
_APPS = "admin-tools/applications"

# The formation pipeline is decided by the Meeting of the Analysts, so the
# review surfaces live under /admin-tools/meeting-of-analysts/.
_MOA = "admin-tools/meeting-of-analysts"

urlpatterns = [
    # --- Applicant ---
    path("apply/", views.apply_start, name="apply_start"),
    path("apply/status/", views.status, name="status"),
    path("apply/<int:pk>/cv/", views.cv_download, name="cv_download"),
    path("apply/<str:track>/", views.apply, name="apply"),

    # --- Applications: read-only review (Meeting of the Analysts) ---
    path(f"{_MOA}/applications/", views.review_queue, name="review_queue"),
    path(f"{_MOA}/applications/<int:pk>/", views.review_detail, name="review_detail"),

    # --- Direct admission (Web Coordinator, NOT the Applications Coordinator:
    #     someone who applied on the site is admitted from their application) ---
    path("admin-tools/web-coordinator/admit/", direct_admit_views.direct_admit,
         name="direct_admit"),

    # --- Applications Coordinator console ---
    path(f"{_APPS}/", coordinator.dashboard, name="coordinator_dashboard"),
    path(f"{_APPS}/help/", coordinator.help_view, name="coordinator_help"),
    path(f"{_APPS}/reset-sandbox/", coordinator.reset_sandbox,
         name="coordinator_reset_sandbox"),
    path(f"{_APPS}/<int:pk>/", coordinator.application_detail,
         name="coordinator_application_detail"),
    # The coordinator's per-application actions (the Meeting's view is read-only).
    path(f"{_APPS}/<int:pk>/assign/", views.review_assign, name="review_assign"),
    path(f"{_APPS}/<int:pk>/decide/", views.review_decide, name="review_decide"),
    path(f"{_APPS}/interview/<int:interview_pk>/report/", views.review_report,
         name="review_report"),
    path(f"{_APPS}/interview/<int:interview_pk>/remove/",
         views.review_remove_interview, name="review_remove_interview"),
    path(f"{_APPS}/<int:pk>/invite/", coordinator.invite, name="coordinator_invite"),
    path(f"{_APPS}/<int:pk>/simulate/", coordinator.simulate,
         name="coordinator_simulate"),
    path(f"{_APPS}/<int:pk>/nudge/", coordinator.nudge, name="coordinator_nudge"),

    # --- Analyst page (interview requests + my interviews) ---
    path("admin-tools/analyst/", analyst.dashboard, name="analyst_dashboard"),
    path("admin-tools/analyst/interview/<int:pk>/", analyst.interview,
         name="analyst_interview"),
    path("admin-tools/analyst/interview/<int:pk>/agree/", analyst.agree,
         name="analyst_agree"),
    path("admin-tools/analyst/interview/<int:pk>/report/", analyst.report,
         name="analyst_report"),
    path(f"{_APPS}/<int:pk>/acknowledge/", coordinator.send_acknowledgment,
         name="coordinator_acknowledge"),
    path(f"{_APPS}/settings/", coordinator.settings_view,
         name="coordinator_settings"),
    path(f"{_APPS}/messages/", coordinator.messages_list,
         name="coordinator_messages"),
    path(f"{_APPS}/messages/<str:key>/", coordinator.message_edit,
         name="coordinator_message_edit"),
]
