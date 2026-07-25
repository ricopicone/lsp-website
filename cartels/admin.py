from django.contrib import admin

from .models import Cartel

# A cartel's invitations and join-requests now live on the Workgroup layer and
# are registered in ``workgroups.admin``.


@admin.register(Cartel)
class CartelAdmin(admin.ModelAdmin):
    list_display = ("__str__", "registration_status", "proposal_status", "closed", "created_at")
    list_filter = ("registration_status", "closed")
    search_fields = ("workgroup__name", "workgroup__slug", "theme")
    autocomplete_fields = ("workgroup",)
    actions = ("approve_selected",)

    @admin.display(description="Proposal")
    def proposal_status(self, obj):
        return obj.get_status_display()

    @admin.action(description="Register selected submitted cartels")
    def approve_selected(self, request, queryset):
        n = 0
        for cartel in queryset.filter(
            registration_status=Cartel.RegistrationStatus.SUBMITTED
        ):
            cartel.approve(request.user)
            n += 1
        self.message_user(request, f"Registered {n} cartel(s).")
