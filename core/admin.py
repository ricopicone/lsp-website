"""Admin for core models."""

from __future__ import annotations

from django.contrib import admin

from .models import Aphorism


@admin.register(Aphorism)
class AphorismAdmin(admin.ModelAdmin):
    list_display = ("short_attribution", "quote", "is_active", "updated_at")
    list_display_links = ("quote",)
    list_editable = ("is_active",)
    list_filter = ("is_active",)
    search_fields = ("quote", "short_attribution", "full_attribution")
    readonly_fields = ("created_at", "updated_at")
