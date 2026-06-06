from django.contrib import admin

from .models import Notification, NotificationPreference


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "recipient", "category", "title", "actor", "read_at", "emailed_at", "created_at",
    )
    list_filter = ("category", "read_at", "emailed_at")
    search_fields = ("recipient__email", "title", "body")
    raw_id_fields = ("recipient", "actor")
    readonly_fields = ("created_at",)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "updated_at")
    search_fields = ("user__email",)
    raw_id_fields = ("user",)
