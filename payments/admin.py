from django.contrib import admin

from .models import DuesPeriod, DuesReminder, Payment, Receipt


class ReceiptInline(admin.StackedInline):
    model = Receipt
    can_delete = False
    readonly_fields = ("receipt_number", "issued_at", "emailed_at")
    extra = 0


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "payment_type",
        "user",
        "registration",
        "amount",
        "currency",
        "status",
        "method",
        "created_at",
    )
    list_filter = ("payment_type", "status", "method", "currency")
    search_fields = (
        "stripe_payment_intent_id",
        "stripe_checkout_session_id",
        "user__email",
        "notes",
    )
    autocomplete_fields = ("user", "registration", "dues_period")
    readonly_fields = ("created_at", "paid_at")
    date_hierarchy = "created_at"
    inlines = [ReceiptInline]


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ("receipt_number", "payment", "issued_at", "emailed_at")
    search_fields = ("receipt_number", "payment__user__email")
    readonly_fields = ("receipt_number", "issued_at")
    date_hierarchy = "issued_at"


@admin.register(DuesPeriod)
class DuesPeriodAdmin(admin.ModelAdmin):
    list_display = (
        "name", "slug", "start_date", "due_date", "end_date",
        "dues_amount", "block_registration_when_unpaid", "is_current",
    )
    list_filter = ("block_registration_when_unpaid",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}

    @admin.display(boolean=True, description="Current?")
    def is_current(self, obj):
        from django.utils import timezone
        today = timezone.now().date()
        return obj.start_date <= today <= obj.end_date


@admin.register(DuesReminder)
class DuesReminderAdmin(admin.ModelAdmin):
    list_display = ("user", "dues_period", "sent_at")
    list_filter = ("dues_period",)
    search_fields = ("user__email",)
    readonly_fields = ("user", "dues_period", "sent_at")
    date_hierarchy = "sent_at"
