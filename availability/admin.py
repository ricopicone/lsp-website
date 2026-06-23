"""Django admin for analyst availability.

This is the raw back office — the lookup table of functions and the full
interval log. The Applications Coordinator's friendlier grid is a separate
console (a later phase); these registrations give staff a complete,
auditable view and a manual escape hatch (do-not-over-automate).
"""

from django.contrib import admin

from .models import (
    AnalystFunction,
    AvailabilitySettings,
    AvailabilitySpan,
    ReminderTemplate,
)


@admin.register(AnalystFunction)
class AnalystFunctionAdmin(admin.ModelAdmin):
    list_display = ("name", "short_label", "display_order", "is_active")
    list_editable = ("display_order", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug")


@admin.register(AvailabilitySpan)
class AvailabilitySpanAdmin(admin.ModelAdmin):
    list_display = (
        "profile",
        "function",
        "status",
        "start_date",
        "end_date",
        "source",
        "created_by",
        "created_at",
    )
    list_filter = ("function", "status", "source", "end_date")
    search_fields = (
        "profile__user__email",
        "profile__user__first_name",
        "profile__user__last_name",
    )
    autocomplete_fields = ("profile", "function", "created_by")
    readonly_fields = ("created_at",)
    date_hierarchy = "start_date"


@admin.register(AvailabilitySettings)
class AvailabilitySettingsAdmin(admin.ModelAdmin):
    list_display = ("__str__", "reminder_mode")


@admin.register(ReminderTemplate)
class ReminderTemplateAdmin(admin.ModelAdmin):
    list_display = ("__str__", "subject", "updated_at")
