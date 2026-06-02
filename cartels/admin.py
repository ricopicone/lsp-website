from django.contrib import admin

from .models import Cartel

# A cartel's invitations and join-requests now live on the Workgroup layer and
# are registered in ``workgroups.admin``.


@admin.register(Cartel)
class CartelAdmin(admin.ModelAdmin):
    list_display = ("__str__", "proposal_status", "closed", "created_at")
    list_filter = ("workgroup__proposal__status", "closed")
    search_fields = ("workgroup__name", "workgroup__slug", "guiding_question")
    autocomplete_fields = ("workgroup",)
    actions = ("approve_selected",)

    @admin.display(description="Status")
    def proposal_status(self, obj):
        return obj.get_status_display()

    @admin.action(description="Approve + publish selected proposed cartels")
    def approve_selected(self, request, queryset):
        n = 0
        for cartel in queryset.filter(
            workgroup__proposal__status=Cartel.Status.PROPOSED
        ):
            cartel.approve(request.user)
            n += 1
        self.message_user(request, f"Approved {n} cartel(s).")
