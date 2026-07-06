from django.contrib import admin

from .models import Advancement


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
