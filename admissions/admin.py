from django.contrib import admin

from .models import Application, ApplicationInterview


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
