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
    path("my-meetings/<str:token>.ics", views.my_calendar_ics, name="my_calendar_ics"),
    path("<slug:slug>/", views.workgroup_detail, name="detail"),
    path("<slug:slug>/join/", views.workgroup_join, name="join"),
    path("<slug:slug>/leave/", views.workgroup_leave, name="leave"),
    path("<slug:slug>/archive/", views.workgroup_archive, name="archive"),
    path("<slug:slug>/unarchive/", views.workgroup_unarchive, name="unarchive"),
    path("<slug:slug>/roster/add/", views.roster_add, name="roster_add"),
    path("<slug:slug>/roster/remove/", views.roster_remove, name="roster_remove"),
    path("<slug:slug>/roster/role/", views.roster_set_role, name="roster_set_role"),
    path("<slug:slug>/open-term/", views.open_reading_group_term, name="open_term"),
    path("<slug:slug>/dates/", views.workgroup_update_dates, name="update_dates"),
    path("<slug:slug>/tasks/add/", views.task_add, name="task_add"),
    path("<slug:slug>/tasks/<int:pk>/toggle/", views.task_toggle, name="task_toggle"),
    path("<slug:slug>/tasks/<int:pk>/assign/", views.task_assign, name="task_assign"),
    path("<slug:slug>/tasks/<int:pk>/delete/", views.task_delete, name="task_delete"),
    path("<slug:slug>/calendar.ics", views.workgroup_calendar_ics, name="calendar_ics"),
    path("<slug:slug>/meetings/add/", views.meeting_add, name="meeting_add"),
    path("<slug:slug>/series/add/", views.series_add, name="series_add"),
    path("<slug:slug>/series/<int:pk>/delete/", views.series_delete, name="series_delete"),
    path("<slug:slug>/meetings/<int:pk>/delete/", views.meeting_delete, name="meeting_delete"),
    path("<slug:slug>/meetings/<int:pk>/cancel/", views.meeting_cancel, name="meeting_cancel"),
    path("<slug:slug>/meetings/<int:pk>/reschedule/", views.meeting_reschedule,
         name="meeting_reschedule"),
    path("<slug:slug>/meetings/<int:pk>/edit/", views.meeting_edit, name="meeting_edit"),
    path("<slug:slug>/meetings/<int:pk>/minutes/", views.meeting_minutes, name="meeting_minutes"),
    # Collaborative working documents (Work tab)
    path("<slug:slug>/docs/new/", views.draft_create, name="draft_create"),
    path("<slug:slug>/docs/<int:pk>/", views.draft_edit, name="draft_edit"),
    path("<slug:slug>/docs/<int:pk>/autosave/", views.draft_autosave, name="draft_autosave"),
    path("<slug:slug>/docs/<int:pk>/version/", views.draft_save_version, name="draft_save_version"),
    path("<slug:slug>/docs/<int:pk>/release/", views.draft_release_lock, name="draft_release_lock"),
    path("<slug:slug>/docs/<int:pk>/publish/", views.draft_publish, name="draft_publish"),
    path("<slug:slug>/docs/<int:pk>/delete/", views.draft_delete, name="draft_delete"),
]
