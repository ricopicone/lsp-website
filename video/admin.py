from django.contrib import admin, messages

from . import daily, services
from .models import DailyRoom, Recording


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


@admin.register(Recording)
class RecordingAdmin(admin.ModelAdmin):
    list_display = (
        "title", "status", "event", "listing_visibility", "content_visibility",
        "keep", "started_at",
    )
    list_filter = ("status", "listing_visibility", "content_visibility", "keep")
    search_fields = ("title", "daily_recording_id", "room_name", "event__title")
    list_editable = ("listing_visibility", "content_visibility", "keep")
    readonly_fields = (
        "daily_recording_id", "room", "room_name", "s3_key", "started_by",
        "started_at", "duration_seconds", "created_at",
    )
    actions = ("delete_recordings_everywhere",)

    @admin.action(description="Delete selected recordings (files + Daily + row)")
    def delete_recordings_everywhere(self, request, queryset):
        n = 0
        for rec in queryset:
            try:
                if rec.s3_key:
                    from core.storage import recordings_storage
                    recordings_storage().delete(rec.s3_key)
                daily.delete_recording(rec.daily_recording_id)
            except Exception:
                pass
            rec.delete()
            n += 1
        self.message_user(request, f"Deleted {n} recording(s).", messages.WARNING)
