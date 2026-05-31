"""Admin for core models."""

from __future__ import annotations

from django.contrib import admin

from .models import Aphorism, StaffRole


@admin.register(Aphorism)
class AphorismAdmin(admin.ModelAdmin):
    list_display = ("short_attribution", "quote", "is_active", "updated_at")
    list_display_links = ("quote",)
    list_editable = ("is_active",)
    list_filter = ("is_active",)
    search_fields = ("quote", "short_attribution", "full_attribution")
    readonly_fields = ("created_at", "updated_at")


@admin.register(StaffRole)
class StaffRoleAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "holder_count")
    filter_horizontal = ("holders",)
    search_fields = ("name", "key", "holders__email")

    @admin.display(description="Holders")
    def holder_count(self, obj):
        return obj.holders.count()

    def get_readonly_fields(self, request, obj=None):
        # ``key`` is code-coupled to a control panel; lock it after creation.
        return ("key",) if obj else ()
