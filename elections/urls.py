from django.urls import path

from . import views_admin, views_board, views_member

app_name = "elections"
_A = "admin-tools/elections"

urlpatterns = [
    path(f"{_A}/", views_admin.admin_index, name="admin"),
    path(f"{_A}/new/", views_admin.admin_new, name="admin_new"),
    path(f"{_A}/help/", views_admin.admin_help, name="admin_help"),
    path(f"{_A}/<slug:slug>/", views_admin.admin_overview, name="admin_overview"),
    path(f"{_A}/<slug:slug>/settings/", views_admin.admin_settings, name="admin_settings"),
    path(f"{_A}/<slug:slug>/nominations/", views_admin.admin_nominations,
         name="admin_nominations"),
    path(f"{_A}/<slug:slug>/roll/", views_admin.admin_roll, name="admin_roll"),
    path(f"{_A}/<slug:slug>/count/", views_admin.admin_count, name="admin_count"),
    path(f"{_A}/<slug:slug>/action/", views_admin.admin_action, name="admin_action"),
    path(f"{_A}/<slug:slug>/nominations/enter/", views_admin.admin_enter_nomination,
         name="admin_enter_nomination"),
    path(f"{_A}/<slug:slug>/override/", views_admin.admin_override, name="admin_override"),
    path("admin-tools/board/elections/", views_board.review, name="board_review"),
    path("admin-tools/board/elections/<int:pk>/decide/", views_board.decide,
         name="board_decide"),
    path("elections/<slug:slug>/nominate/", views_member.nominate, name="nominate"),
    path("elections/<slug:slug>/withdraw/", views_member.withdraw, name="withdraw"),
    path("elections/<slug:slug>/ballot/", views_member.ballot, name="ballot"),
]
