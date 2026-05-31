from django.urls import path

from . import views

app_name = "workgroups"

urlpatterns = [
    path("", views.workgroup_list, name="list"),
    # Per-kind directories. Listed before the catch-all detail route so these
    # reserved words win; we don't mint workgroup slugs that collide with them.
    path("seminars/", views.workgroup_kind_list, {"kind": "seminar"},
         name="kind_seminars"),
    path("cartels/", views.workgroup_kind_list, {"kind": "cartel"},
         name="kind_cartels"),
    path("committees/", views.workgroup_kind_list, {"kind": "committee"},
         name="kind_committees"),
    path("working-groups/", views.workgroup_kind_list, {"kind": "working_group"},
         name="kind_working_groups"),
    path("reading-groups/", views.workgroup_kind_list, {"kind": "reading_group"},
         name="kind_reading_groups"),
    path("<slug:slug>/", views.workgroup_detail, name="detail"),
]
