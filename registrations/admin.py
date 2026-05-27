from django.contrib import admin

from .models import Registration


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "event",
        "price_tier",
        "quoted_amount",
        "status",
        "created_at",
    )
    list_filter = ("status", "event")
    search_fields = (
        "user__email",
        "user__first_name",
        "user__last_name",
        "event__title",
    )
    autocomplete_fields = ("user", "event", "price_tier", "pricing_code")
    filter_horizontal = ("sessions",)
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
