from django.contrib import admin

from .models import Workgroup, WorkgroupMeeting, WorkgroupMembership, WorkgroupTask


class WorkgroupMembershipInline(admin.TabularInline):
    model = WorkgroupMembership
    extra = 0
    autocomplete_fields = ("user",)
    fields = ("user", "role", "start_date", "end_date")


@admin.register(Workgroup)
class WorkgroupAdmin(admin.ModelAdmin):
    list_display = (
        "name", "kind", "landing_visibility", "content_visibility",
        "start_date", "end_date",
    )
    list_filter = ("kind", "landing_visibility", "content_visibility")
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("parent",)
    inlines = (WorkgroupMembershipInline,)
    fieldsets = (
        (None, {"fields": ("kind", "name", "slug", "description", "parent",
                           "auto_member_role")}),
        ("Visibility", {"fields": ("landing_visibility", "content_visibility")}),
        ("Term", {"fields": ("start_date", "end_date")}),
        ("Capabilities", {
            "fields": (
                "has_channel", "has_works", "has_files", "has_calendar",
                "has_minutes", "has_tasks", "has_decisions",
            ),
            "description": "Defaults are seeded by kind on creation; edit freely.",
        }),
    )

    def get_changeform_initial_data(self, request):
        """Seed the capability toggles from the kind when adding via admin.

        The kind isn't known until the form is submitted on a blank add, so we
        also apply the seed in ``save_model`` for newly-added rows.
        """
        return super().get_changeform_initial_data(request)

    def save_model(self, request, obj, form, change):
        if not change:
            for field, value in Workgroup.kind_toggle_defaults(obj.kind).items():
                # Only seed toggles the user left at the field default.
                if field not in form.changed_data:
                    setattr(obj, field, value)
        super().save_model(request, obj, form, change)


@admin.register(WorkgroupMembership)
class WorkgroupMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "workgroup", "role", "start_date", "end_date", "is_active")
    list_filter = ("role", "workgroup__kind")
    search_fields = ("user__email", "user__first_name", "user__last_name", "workgroup__name")
    autocomplete_fields = ("user", "workgroup")


@admin.register(WorkgroupTask)
class WorkgroupTaskAdmin(admin.ModelAdmin):
    list_display = ("title", "workgroup", "done", "due_date", "created_at")
    list_filter = ("done", "workgroup__kind")
    search_fields = ("title", "workgroup__name")
    autocomplete_fields = ("workgroup", "assignees", "created_by")


@admin.register(WorkgroupMeeting)
class WorkgroupMeetingAdmin(admin.ModelAdmin):
    list_display = ("__str__", "workgroup", "starts_at", "ends_at")
    list_filter = ("workgroup__kind",)
    search_fields = ("title", "workgroup__name", "location")
    autocomplete_fields = ("workgroup", "created_by")
