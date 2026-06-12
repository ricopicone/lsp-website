from django.contrib import admin

from .models import (
    MessageTemplate,
    ReferralListMember,
    ReferralRequest,
    ReferralResponse,
    ReferralSettings,
)


class ReferralResponseInline(admin.TabularInline):
    model = ReferralResponse
    extra = 0
    raw_id_fields = ("member", "recorded_by")


@admin.register(ReferralRequest)
class ReferralRequestAdmin(admin.ModelAdmin):
    list_display = (
        "reference", "name", "location", "status", "created_at",
        "responses_due_at", "purged_at",
    )
    list_filter = ("status",)
    search_fields = ("reference", "name", "email", "location")
    readonly_fields = ("reference", "created_at")
    inlines = [ReferralResponseInline]


@admin.register(ReferralListMember)
class ReferralListMemberAdmin(admin.ModelAdmin):
    list_display = ("user", "is_active", "added_at", "onboarded_at")
    list_filter = ("is_active",)
    search_fields = ("user__email", "user__first_name", "user__last_name")
    raw_id_fields = ("user",)


@admin.register(ReferralResponse)
class ReferralResponseAdmin(admin.ModelAdmin):
    list_display = ("request", "member", "available", "created_at", "recorded_by")
    list_filter = ("available",)
    raw_id_fields = ("request", "member", "recorded_by")


@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ("key", "subject", "updated_at")


@admin.register(ReferralSettings)
class ReferralSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "__str__", "ack_mode", "distribution_mode", "followup_mode",
        "onboarding_mode", "response_window_days", "retention_months",
    )
