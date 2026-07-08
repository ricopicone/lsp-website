from django.urls import path

from . import views

app_name = "cartels"

urlpatterns = [
    path("", views.index, name="index"),
    path("propose/", views.propose, name="propose"),
    path("member-search/", views.member_search, name="member_search"),
    path("review/", views.review_queue, name="review_queue"),
    path("review/<int:pk>/decide/", views.review_decide, name="review_decide"),
    path("review/<int:pk>/feedback/", views.coordinator_feedback, name="coordinator_feedback"),
    path("<slug:slug>/", views.detail, name="detail"),
    path("<slug:slug>/edit/", views.edit, name="edit"),
    path("<slug:slug>/manage/", views.manage, name="manage"),
    path("<slug:slug>/plus-one/", views.set_plus_one, name="set_plus_one"),
    path("<slug:slug>/plus-one/external/", views.add_external_plus_one,
         name="add_external_plus_one"),
    path("<slug:slug>/plus-one/external/<int:pk>/invite/", views.invite_external_plus_one,
         name="invite_external_plus_one"),
    path("<slug:slug>/plus-one/external/<int:pk>/remove/", views.remove_external_plus_one,
         name="remove_external_plus_one"),
    path("<slug:slug>/apply/", views.apply, name="apply"),
    path("<slug:slug>/submit/", views.submit, name="submit"),
    path("<slug:slug>/question/", views.set_question, name="set_question"),
    path("<slug:slug>/accept-invitation/", views.accept_invitation, name="accept_invitation"),
    path("<slug:slug>/requests/<int:pk>/decide/", views.decide_request, name="decide_request"),
]
