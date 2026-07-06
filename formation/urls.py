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

    # --- Advancement: advisor side ---
    path("formation/advise/", views.advise_queue, name="advise_queue"),
    path("formation/advise/<int:pk>/present/", views.advise_present,
         name="advise_present"),

    # --- Advancement review (Meeting of the Analysts) ---
    path(f"{_MOA}/advancements/", views.advancement_queue, name="advancement_queue"),
    path(f"{_MOA}/advancements/<int:pk>/", views.advancement_detail,
         name="advancement_detail"),
    path(f"{_MOA}/advancements/<int:pk>/decide/", views.advancement_decide,
         name="advancement_decide"),
]
