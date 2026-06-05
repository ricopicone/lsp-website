from django.contrib import admin, messages

from . import daily, services
from .models import DailyRoom


@admin.register(DailyRoom)
class DailyRoomAdmin(admin.ModelAdmin):
    list_display = ("name", "workgroup", "provider_created", "created_at")
    search_fields = ("name", "workgroup__name", "workgroup__slug")
    readonly_fields = ("name", "url", "provider_created", "created_at", "last_synced_at")
    actions = ("reprovision_rooms", "delete_remote_rooms")

    @admin.action(description="Re-provision selected rooms on Daily")
    def reprovision_rooms(self, request, queryset):
        n = 0
        for room in queryset:
            room.provider_created = False
            room.save(update_fields=["provider_created"])
            if services.ensure_room(room.workgroup) is not None:
                n += 1
        self.message_user(request, f"Re-provisioned {n} room(s).", messages.SUCCESS)

    @admin.action(description="Delete selected rooms on Daily (keeps the row)")
    def delete_remote_rooms(self, request, queryset):
        n = 0
        for room in queryset:
            try:
                daily.delete_room(room.name)
            except daily.DailyError:
                continue
            room.provider_created = False
            room.save(update_fields=["provider_created"])
            n += 1
        self.message_user(request, f"Deleted {n} remote room(s).", messages.WARNING)
