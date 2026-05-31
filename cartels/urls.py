from django.urls import path

from . import views

app_name = "cartels"

urlpatterns = [
    path("", views.index, name="index"),
    path("propose/", views.propose, name="propose"),
    path("review/", views.review_queue, name="review_queue"),
    path("review/<int:pk>/decide/", views.review_decide, name="review_decide"),
    path("<slug:slug>/", views.detail, name="detail"),
    path("<slug:slug>/apply/", views.apply, name="apply"),
    path("<slug:slug>/accept-invitation/", views.accept_invitation, name="accept_invitation"),
    path("<slug:slug>/requests/<int:pk>/decide/", views.decide_request, name="decide_request"),
]
