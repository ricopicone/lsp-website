from django.urls import path

from . import views

app_name = "devapi"

urlpatterns = [
    path("whoami/", views.whoami, name="whoami"),
    path("suggestions/", views.suggestion_list, name="suggestion_list"),
    path("suggestions/stats/", views.suggestion_stats, name="suggestion_stats"),
    path("suggestions/<int:pk>/", views.suggestion_detail_view, name="suggestion_detail"),
]
