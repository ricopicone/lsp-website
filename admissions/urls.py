from django.urls import path

from . import views

app_name = "admissions"

urlpatterns = [
    # Applicant
    path("apply/", views.apply_start, name="apply_start"),
    path("apply/status/", views.status, name="status"),
    path("apply/<int:pk>/cv/", views.cv_download, name="cv_download"),
    path("apply/<str:track>/", views.apply, name="apply"),
    # Board review
    path("admin-tools/board/applications/", views.review_queue, name="review_queue"),
    path("admin-tools/board/applications/<int:pk>/", views.review_detail, name="review_detail"),
    path("admin-tools/board/applications/<int:pk>/assign/", views.review_assign,
         name="review_assign"),
    path("admin-tools/board/applications/<int:pk>/decide/", views.review_decide,
         name="review_decide"),
    path("admin-tools/board/applications/interview/<int:interview_pk>/report/",
         views.review_report, name="review_report"),
    path("admin-tools/board/applications/interview/<int:interview_pk>/remove/",
         views.review_remove_interview, name="review_remove_interview"),
]
