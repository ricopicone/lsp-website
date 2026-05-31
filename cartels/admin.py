from django.contrib import admin

from .models import Cartel, CartelInvitation, CartelJoinRequest


class CartelInvitationInline(admin.TabularInline):
    model = CartelInvitation
    extra = 0
    autocomplete_fields = ("invited_user",)
    readonly_fields = ("created_at", "accepted_at")


class CartelJoinRequestInline(admin.TabularInline):
    model = CartelJoinRequest
    extra = 0
    autocomplete_fields = ("applicant", "decided_by")
    readonly_fields = ("created_at", "decided_at")


@admin.register(Cartel)
class CartelAdmin(admin.ModelAdmin):
    list_display = ("__str__", "status", "generator", "closed", "reviewed_by", "created_at")
    list_filter = ("status", "closed")
    search_fields = ("workgroup__name", "workgroup__slug", "guiding_question")
    autocomplete_fields = ("workgroup", "generator", "reviewed_by")
    inlines = (CartelInvitationInline, CartelJoinRequestInline)
    actions = ("approve_selected",)

    @admin.action(description="Approve + publish selected proposed cartels")
    def approve_selected(self, request, queryset):
        n = 0
        for cartel in queryset.filter(status=Cartel.Status.PROPOSED):
            cartel.approve(request.user)
            n += 1
        self.message_user(request, f"Approved {n} cartel(s).")


@admin.register(CartelJoinRequest)
class CartelJoinRequestAdmin(admin.ModelAdmin):
    list_display = ("applicant", "cartel", "status", "decided_by", "created_at", "decided_at")
    list_filter = ("status",)
    search_fields = ("applicant__email", "cartel__workgroup__name")
    autocomplete_fields = ("cartel", "applicant", "decided_by")
