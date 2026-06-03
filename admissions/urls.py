from django.urls import path

from . import views

app_name = "admissions"

# The formation pipeline is decided by the Meeting of the Analysts, so the
# review surfaces live under /admin-tools/meeting-of-analysts/.
_MOA = "admin-tools/meeting-of-analysts"

urlpatterns = [
    # --- Applicant ---
    path("apply/", views.apply_start, name="apply_start"),
    path("apply/status/", views.status, name="status"),
    path("apply/<int:pk>/cv/", views.cv_download, name="cv_download"),
    path("apply/<str:track>/", views.apply, name="apply"),

    # --- Advancement: member side ---
    path("formation/", views.advancement, name="advancement"),
    path("formation/<int:pk>/withdraw/", views.advancement_withdraw,
         name="advancement_withdraw"),
    path("formation/<int:pk>/palimpsest/", views.palimpsest_download,
         name="palimpsest_download"),

    # --- Advancement: advisor side ---
    path("formation/advise/", views.advise_queue, name="advise_queue"),
    path("formation/advise/<int:pk>/present/", views.advise_present,
         name="advise_present"),

    # --- Application review (Meeting of the Analysts) ---
    path(f"{_MOA}/applications/", views.review_queue, name="review_queue"),
    path(f"{_MOA}/applications/<int:pk>/", views.review_detail, name="review_detail"),
    path(f"{_MOA}/applications/<int:pk>/assign/", views.review_assign,
         name="review_assign"),
    path(f"{_MOA}/applications/<int:pk>/decide/", views.review_decide,
         name="review_decide"),
    path(f"{_MOA}/applications/interview/<int:interview_pk>/report/",
         views.review_report, name="review_report"),
    path(f"{_MOA}/applications/interview/<int:interview_pk>/remove/",
         views.review_remove_interview, name="review_remove_interview"),

    # --- Advancement review (Meeting of the Analysts) ---
    path(f"{_MOA}/advancements/", views.advancement_queue, name="advancement_queue"),
    path(f"{_MOA}/advancements/<int:pk>/", views.advancement_detail,
         name="advancement_detail"),
    path(f"{_MOA}/advancements/<int:pk>/decide/", views.advancement_decide,
         name="advancement_decide"),
]
