from django.contrib import admin

from .models import (
    MeetingSeries,
    Visibility,
    Workgroup,
    WorkgroupDecision,
    WorkgroupFile,
    WorkgroupFileVersion,
    WorkgroupInvitation,
    WorkgroupJoinRequest,
    WorkgroupMeeting,
    WorkgroupMembership,
    WorkgroupProposal,
    WorkgroupTask,
)


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
        ("Files", {
            "fields": ("file_quota_bytes",),
            "description": "Shared-files storage quota (bytes). Raise when a "
            "group requests more space (default 200 MB = 209715200).",
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
            # Reading groups: public landing (page is visible to all), roster +
            # content members-only — unless the staffer set them explicitly.
            if obj.kind == Workgroup.Kind.READING_GROUP:
                if "landing_visibility" not in form.changed_data:
                    obj.landing_visibility = Visibility.PUBLIC
                if "content_visibility" not in form.changed_data:
                    obj.content_visibility = Visibility.MEMBERS
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
    list_display = ("__str__", "workgroup", "starts_at", "ends_at", "cancelled")
    list_filter = ("workgroup__kind", "cancelled")
    search_fields = ("title", "workgroup__name", "location")
    autocomplete_fields = ("workgroup", "series", "created_by")


@admin.register(MeetingSeries)
class MeetingSeriesAdmin(admin.ModelAdmin):
    list_display = ("__str__", "workgroup", "frequency", "start_date", "end_date")
    list_filter = ("frequency", "workgroup__kind")
    search_fields = ("title", "workgroup__name")
    autocomplete_fields = ("workgroup", "created_by")


@admin.register(WorkgroupProposal)
class WorkgroupProposalAdmin(admin.ModelAdmin):
    list_display = ("workgroup", "status", "proposed_by", "reviewed_by",
                    "reviewed_at", "created_at")
    list_filter = ("status", "workgroup__kind")
    search_fields = ("workgroup__name", "workgroup__slug")
    autocomplete_fields = ("workgroup", "proposed_by", "reviewed_by")


@admin.register(WorkgroupInvitation)
class WorkgroupInvitationAdmin(admin.ModelAdmin):
    list_display = ("invited_user", "workgroup", "created_by", "created_at", "accepted_at")
    list_filter = ("workgroup__kind",)
    search_fields = ("invited_user__email", "workgroup__name")
    autocomplete_fields = ("workgroup", "invited_user", "created_by")


@admin.register(WorkgroupJoinRequest)
class WorkgroupJoinRequestAdmin(admin.ModelAdmin):
    list_display = ("applicant", "workgroup", "status", "decided_by",
                    "created_at", "decided_at")
    list_filter = ("status", "workgroup__kind")
    search_fields = ("applicant__email", "workgroup__name")
    autocomplete_fields = ("workgroup", "applicant", "decided_by")


class WorkgroupFileVersionInline(admin.TabularInline):
    model = WorkgroupFileVersion
    extra = 0
    fields = ("number", "blob", "size", "uploaded_by", "uploaded_at")
    readonly_fields = ("uploaded_at",)
    autocomplete_fields = ("uploaded_by",)


@admin.register(WorkgroupFile)
class WorkgroupFileAdmin(admin.ModelAdmin):
    list_display = ("name", "workgroup", "version_count", "size", "created_by", "updated_at")
    list_filter = ("workgroup__kind",)
    search_fields = ("name", "workgroup__name")
    autocomplete_fields = ("workgroup", "created_by")
    inlines = (WorkgroupFileVersionInline,)


@admin.register(WorkgroupDecision)
class WorkgroupDecisionAdmin(admin.ModelAdmin):
    list_display = ("title", "workgroup", "status", "decided_on", "meeting", "created_by")
    list_filter = ("status", "workgroup__kind")
    search_fields = ("title", "detail", "workgroup__name")
    autocomplete_fields = ("workgroup", "meeting", "created_by")
