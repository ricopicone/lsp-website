from django.contrib import admin

from .models import Advancement, Application, ApplicationInterview


class InterviewInline(admin.TabularInline):
    model = ApplicationInterview
    extra = 0
    autocomplete_fields = ("interviewer",)


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("applicant", "track", "status", "submitted_at", "decided_at")
    list_filter = ("track", "status")
    search_fields = (
        "applicant__email", "applicant__first_name", "applicant__last_name",
    )
    autocomplete_fields = ("applicant", "decided_by")
    inlines = [InterviewInline]
    readonly_fields = ("created_at", "updated_at")


@admin.register(ApplicationInterview)
class ApplicationInterviewAdmin(admin.ModelAdmin):
    list_display = ("application", "interviewer", "completed_at")
    search_fields = ("application__applicant__email", "interviewer__email")
    autocomplete_fields = ("application", "interviewer")


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
