from django.contrib import admin

from .models import (
    Advancement,
    AdvisorNote,
    ControlAnalysis,
    ExternalActivity,
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
        "control_years_target",
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
