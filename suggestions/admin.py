from django.contrib import admin
from django.utils import timezone

from .export import write_briefs
from .models import Suggestion

#: Default folder for admin-triggered exports (gitignored; see .gitignore).
EXPORT_DIR = "suggestions-briefs"


@admin.register(Suggestion)
class SuggestionAdmin(admin.ModelAdmin):
    list_display = (
        "title", "kind", "status", "priority", "submitted_by", "page_url",
        "exported_at", "created_at",
    )
    list_filter = ("status", "kind", "priority")
    search_fields = ("title", "body", "submitted_by__email", "page_url")
    readonly_fields = ("created_at", "updated_at", "exported_at", "context")
    autocomplete_fields = ("submitted_by", "reviewed_by")
    actions = (
        "export_to_brief", "mark_acknowledged", "mark_done", "mark_declined",
    )

    @admin.action(description="Export selected to Claude Code brief")
    def export_to_brief(self, request, queryset):
        written = write_briefs(queryset, EXPORT_DIR)
        self.message_user(
            request,
            f"Wrote {len(written)} brief(s) + INDEX.md to ./{EXPORT_DIR}/.",
        )

    def _set_status(self, request, queryset, status, label):
        n = queryset.update(
            status=status, reviewed_by=request.user, reviewed_at=timezone.now()
        )
        self.message_user(request, f"Marked {n} suggestion(s) {label}.")

    @admin.action(description="Mark acknowledged")
    def mark_acknowledged(self, request, queryset):
        self._set_status(request, queryset, Suggestion.Status.ACKNOWLEDGED, "acknowledged")

    @admin.action(description="Mark done")
    def mark_done(self, request, queryset):
        self._set_status(request, queryset, Suggestion.Status.DONE, "done")

    @admin.action(description="Mark declined")
    def mark_declined(self, request, queryset):
        self._set_status(request, queryset, Suggestion.Status.DECLINED, "declined")
