from django import forms
from django.contrib import admin

from .models import (
    Event,
    EventMemberSpeaker,
    EventProposal,
    PriceTier,
    PricingCode,
    Program,
    ProposalReading,
    ProposalSpeaker,
    Session,
    Speaker,
)


class ProposalReadingInline(admin.TabularInline):
    model = ProposalReading
    extra = 0


class ProposalSpeakerInline(admin.TabularInline):
    model = ProposalSpeaker
    extra = 0


@admin.register(EventProposal)
class EventProposalAdmin(admin.ModelAdmin):
    list_display = ("title", "event_type", "proposed_by", "status", "start_date",
                    "end_date", "continues_seminar", "minted_event", "created_at")
    list_filter = ("status", "event_type", "location_kind")
    search_fields = ("title", "proposed_by__email")
    autocomplete_fields = ("proposed_by", "reviewed_by", "continues_seminar",
                           "faculty", "minted_event")
    inlines = (ProposalReadingInline, ProposalSpeakerInline)


class EventAdminForm(forms.ModelForm):
    """Adds a ``faculty`` editor backed by the workgroup roster (faculty is no
    longer a model field — see ``Event.set_faculty``)."""

    faculty = forms.ModelMultipleChoiceField(
        queryset=None, required=False,
        widget=admin.widgets.FilteredSelectMultiple("faculty", is_stacked=False),
        help_text="LSP instructors — stored as a FACULTY role on the event's workgroup.",
    )

    class Meta:
        model = Event
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from accounts.models import User

        self.fields["faculty"].queryset = User.objects.filter(
            is_active=True
        ).order_by("last_name", "first_name")
        if self.instance.pk:
            self.fields["faculty"].initial = self.instance.faculty_members()


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
    form = EventAdminForm
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
    filter_horizontal = ("speakers",)
    inlines = [SessionInline, PriceTierInline, EventMemberSpeakerInline]
    actions = ("create_workspace",)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # Faculty is roster-backed; reconcile after the instance + m2m are saved
        # (ensure_workgroup needs a pk).
        form.instance.set_faculty(form.cleaned_data.get("faculty", []))

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
