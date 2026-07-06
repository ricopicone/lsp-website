from django.contrib import admin

from .models import Advancement, ControlAnalysis, ExternalActivity, FormationSettings


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


admin.site.register(FormationSettings)


@admin.register(ControlAnalysis)
class ControlAnalysisAdmin(admin.ModelAdmin):
    list_display = ("member", "supervisor_name", "modality", "start_date", "end_date")
    search_fields = ("member__email", "supervisor_name")


@admin.register(ExternalActivity)
class ExternalActivityAdmin(admin.ModelAdmin):
    list_display = ("member", "kind", "title", "venue", "start_date", "end_date")
    list_filter = ("kind",)
    search_fields = ("member__email", "title", "venue")
