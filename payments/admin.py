from django.contrib import admin

from .models import Payment, Receipt


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
    autocomplete_fields = ("user", "registration")
    readonly_fields = ("created_at", "paid_at")
    date_hierarchy = "created_at"
    inlines = [ReceiptInline]


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ("receipt_number", "payment", "issued_at", "emailed_at")
    search_fields = ("receipt_number", "payment__user__email")
    readonly_fields = ("receipt_number", "issued_at")
    date_hierarchy = "issued_at"
