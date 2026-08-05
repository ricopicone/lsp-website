from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("speakers/invitation/<str:token>/",
         views.speaker_invitation_accept, name="speaker_invitation_accept"),
    path("", views.event_list, name="list"),
    path("<slug:slug>/speakers/<int:speaker_id>/invite/",
         views.speaker_invite, name="speaker_invite"),
    path("<slug:slug>/", views.event_detail, name="detail"),
    path("<slug:slug>/edit/", views.event_edit, name="edit"),
    path("<slug:slug>/edit/schedule/", views.event_edit_schedule, name="edit_schedule"),
    path("<slug:slug>/feature-image/", views.event_feature_image, name="feature_image"),
    path("<slug:slug>/ce-organizations/add/",
         views.ce_organization_add, name="ce_organization_add"),
    path("<slug:slug>/ce-organizations/<int:pk>/",
         views.ce_organization_edit, name="ce_organization_edit"),
    path("<slug:slug>/roster.csv", views.event_roster_csv, name="roster_csv"),
    path("<slug:slug>/codes/", views.event_generate_code, name="generate_code"),
    path("<slug:slug>/check-code/", views.check_pricing_code, name="check_code"),
]
