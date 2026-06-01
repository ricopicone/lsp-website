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
    path("<slug:slug>/join/", views.workgroup_join, name="join"),
    path("<slug:slug>/leave/", views.workgroup_leave, name="leave"),
    path("<slug:slug>/open-term/", views.open_reading_group_term, name="open_term"),
    path("<slug:slug>/dates/", views.workgroup_update_dates, name="update_dates"),
    path("<slug:slug>/tasks/add/", views.task_add, name="task_add"),
    path("<slug:slug>/tasks/<int:pk>/toggle/", views.task_toggle, name="task_toggle"),
    path("<slug:slug>/tasks/<int:pk>/assign/", views.task_assign, name="task_assign"),
    path("<slug:slug>/tasks/<int:pk>/delete/", views.task_delete, name="task_delete"),
    path("<slug:slug>/meetings/add/", views.meeting_add, name="meeting_add"),
    path("<slug:slug>/meetings/<int:pk>/delete/", views.meeting_delete, name="meeting_delete"),
]
