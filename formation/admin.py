from django.contrib import admin

from .models import (
    Advancement,
    AdvisorNote,
    ControlAnalysis,
    ExternalActivity,
    ExternalControlAnalyst,
    FormationSettings,
)


@admin.register(Advancement)
class AdvancementAdmin(admin.ModelAdmin):
    list_display = ("member", "kind", "status", "advisor", "presented_at", "decided_at")
    list_filter = ("kind", "status")
    search_fields = (
        "member__email", "member__first_name", "member__last_name",
        "advisor__email",
    )
    autocomplete_fields = ("member", "advisor", "decided_by")
    readonly_fields = ("created_at", "updated_at", "from_role")


@admin.register(FormationSettings)
class FormationSettingsAdmin(admin.ModelAdmin):
    fields = (
        "four_year_threshold",
        "two_year_threshold",
        "analyst_formation_doc",
        "scholar_formation_doc",
    )


@admin.register(ControlAnalysis)
class ControlAnalysisAdmin(admin.ModelAdmin):
    list_display = ("member", "supervisor_name", "modality", "start_date", "end_date")
    search_fields = ("member__email", "supervisor_name")


@admin.register(ExternalActivity)
class ExternalActivityAdmin(admin.ModelAdmin):
    list_display = ("member", "kind", "title", "venue", "start_date", "end_date")
    list_filter = ("kind",)
    search_fields = ("member__email", "title", "venue")


@admin.register(AdvisorNote)
class AdvisorNoteAdmin(admin.ModelAdmin):
    list_display = ("advisee", "author", "created_at")
    search_fields = ("advisee__email", "author__email", "body")
    autocomplete_fields = ("advisee", "author")
    readonly_fields = ("created_at",)


@admin.register(ExternalControlAnalyst)
class ExternalControlAnalystAdmin(admin.ModelAdmin):
    list_display = ("name", "member", "status", "requested_at", "decided_at")
    list_filter = ("status",)
    search_fields = ("name", "member__email", "member__last_name")
    actions = ("approve_selected", "decline_selected")

    @admin.action(description="Approve selected external analysts")
    def approve_selected(self, request, queryset):
        from formation.control import decide_external
        for obj in queryset.filter(status=ExternalControlAnalyst.Status.REQUESTED):
            decide_external(obj, approve=True, by=request.user, note="Approved via admin.")

    @admin.action(description="Decline selected external analysts")
    def decline_selected(self, request, queryset):
        from formation.control import decide_external
        for obj in queryset.filter(status=ExternalControlAnalyst.Status.REQUESTED):
            decide_external(obj, approve=False, by=request.user, note="Declined via admin.")
