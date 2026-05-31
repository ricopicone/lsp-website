from django.contrib import admin

from .models import (
    Event,
    EventMemberSpeaker,
    PriceTier,
    PricingCode,
    Program,
    Session,
    Speaker,
)


class SessionInline(admin.TabularInline):
    model = Session
    extra = 0
    fields = ("sequence", "title", "start_at", "end_at", "location")
    ordering = ("sequence", "start_at")


class PriceTierInline(admin.TabularInline):
    model = PriceTier
    extra = 0
    fields = (
        "audience",
        "session",
        "base_amount",
        "sliding_scale",
        "minimum_amount",
        "covered_by_tuition",
    )
    autocomplete_fields = ("session",)


class EventMemberSpeakerInline(admin.TabularInline):
    model = EventMemberSpeaker
    extra = 0
    fields = ("user", "sort_order")
    autocomplete_fields = ("user",)
    verbose_name = "Member speaker (linked LSP user)"
    verbose_name_plural = (
        "Member speakers (linked LSP users — bio comes from the user's Profile; "
        "use Profile.event_bio for an alternate speaker-only bio)"
    )


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "event_type",
        "status",
        "published",
        "start_date",
        "end_date",
        "session_count",
    )
    list_filter = ("event_type", "visibility", "status", "published", "format", "program")
    search_fields = ("title", "slug", "description")
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ("faculty", "speakers")
    inlines = [SessionInline, PriceTierInline, EventMemberSpeakerInline]
    actions = ("create_workspace",)

    @admin.display(description="Sessions")
    def session_count(self, obj):
        return obj.sessions.count()

    @admin.action(description="Create workspace (discussion channel) for selected events")
    def create_workspace(self, request, queryset):
        created = 0
        for event in queryset:
            if event.workgroup_id is None:
                event.ensure_workgroup()
                created += 1
        self.message_user(
            request,
            f"Created {created} workspace(s); "
            f"{queryset.count() - created} already had one.",
        )


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("event", "sequence", "title", "start_at", "end_at", "location")
    list_filter = ("event",)
    search_fields = ("event__title", "title", "location")
    date_hierarchy = "start_at"
    autocomplete_fields = ("event",)


@admin.register(PriceTier)
class PriceTierAdmin(admin.ModelAdmin):
    list_display = (
        "event",
        "session",
        "audience",
        "base_amount",
        "sliding_scale",
        "covered_by_tuition",
    )
    list_filter = ("event", "audience", "sliding_scale", "covered_by_tuition")
    autocomplete_fields = ("event", "session")
    search_fields = ("event__title", "audience")


@admin.register(Speaker)
class SpeakerAdmin(admin.ModelAdmin):
    list_display = ("name", "affiliation", "email", "public")
    list_filter = ("public",)
    search_fields = ("name", "affiliation", "email", "bio")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(PricingCode)
class PricingCodeAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "event",
        "pricing_mode",
        "amount_or_percent",
        "valid_until",
        "uses_remaining",
        "issued_by",
    )
    list_filter = ("event", "pricing_mode")
    search_fields = ("code", "event__title", "issued_by__email")
    readonly_fields = ("code", "created_at")
    autocomplete_fields = ("event", "issued_by", "restricted_to_user")


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("academic_year", "name", "published", "publish_date", "event_count")
    list_filter = ("published",)
    search_fields = ("academic_year", "name")
    readonly_fields = ("created_at",)

    @admin.display(description="Events")
    def event_count(self, obj):
        return obj.events.count()
