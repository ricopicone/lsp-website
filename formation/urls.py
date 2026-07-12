from django.urls import path

from . import views

app_name = "formation"
_MOA = "admin-tools/meeting-of-analysts"

urlpatterns = [
    # --- Member formation hub (advisor + advancement + tuition + groups) ---
    path("formation/", views.formation, name="formation"),
    path("formation/demande/", views.advancement, name="advancement"),
    path("formation/<int:pk>/withdraw/", views.advancement_withdraw,
         name="advancement_withdraw"),
    path("formation/<int:pk>/palimpsest/", views.palimpsest_download,
         name="palimpsest_download"),
    path("formation/control/add/", views.control_add, name="control_add"),
    path("formation/control/<int:pk>/edit/", views.control_edit, name="control_edit"),
    path("formation/control/<int:pk>/delete/", views.control_delete, name="control_delete"),
    path("formation/external/add/", views.external_add, name="external_add"),
    path("formation/external/<int:pk>/edit/", views.external_edit, name="external_edit"),
    path("formation/external/<int:pk>/delete/", views.external_delete, name="external_delete"),
    path("formation/control/external-analyst/request/",
         views.external_analyst_request, name="external_analyst_request"),

    # --- Advancement: advisor side ---
    path("formation/advise/", views.advise_queue, name="advise_queue"),
    path("formation/advise/<int:pk>/present/", views.advise_present,
         name="advise_present"),

    # --- Advisor View: read-only advisee record + private notes ---
    path("formation/advisees/", views.advisees, name="advisees"),
    path("formation/advisees/<int:pk>/", views.advisee_detail, name="advisee_detail"),
    path("formation/advisees/<int:pk>/note/", views.advisee_note_add,
         name="advisee_note_add"),

    # --- Advancement review (Meeting of the Analysts) ---
    path(f"{_MOA}/advancements/", views.advancement_queue, name="advancement_queue"),
    path(f"{_MOA}/advancements/<int:pk>/", views.advancement_detail,
         name="advancement_detail"),
    path(f"{_MOA}/advancements/<int:pk>/decide/", views.advancement_decide,
         name="advancement_decide"),
]
