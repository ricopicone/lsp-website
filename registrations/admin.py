from django.contrib import admin, messages
from django.utils import timezone

from payments import notifications as notify_payments

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
    actions = ("comp_selected_registrations",)

    @admin.action(description="Comp selected registrations (mark COMPED + email)")
    def comp_selected_registrations(self, request, queryset):
        """Comp registrations not already paid/comped/cancelled/refunded (REG-14)."""
        compable = queryset.filter(status=Registration.Status.AWAITING_PAYMENT)
        skipped = queryset.exclude(
            status=Registration.Status.AWAITING_PAYMENT,
        ).count()
        note_line = (
            f"\n[{timezone.now().date().isoformat()}] Comped by "
            f"{request.user.email} via admin."
        )
        succeeded = 0
        failed = 0
        for reg in compable:
            reg.status = Registration.Status.COMPED
            reg.staff_notes = (reg.staff_notes or "") + note_line
            reg.save(update_fields=("status", "staff_notes"))
            try:
                notify_payments.registration_confirmed(reg)
            except Exception:
                failed += 1
            succeeded += 1
        msg = f"Comped {succeeded} registration(s)."
        if skipped:
            msg += (
                f" Skipped {skipped} that weren't in 'awaiting payment'."
            )
        if failed:
            msg += f" Email failed for {failed} (status updated regardless)."
        self.message_user(request, msg, level=messages.SUCCESS)
