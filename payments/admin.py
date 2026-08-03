from django.contrib import admin, messages

from .models import (
    Charge,
    DuesPeriod,
    DuesReminder,
    LedgerSubmission,
    Payment,
    PaymentMemberAction,
    Receipt,
    RegistrationInstallment,
    TuitionEnrollment,
    TuitionInstallment,
    TuitionPeriod,
    TuitionReminder,
)
from .operations import complete_payment


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
    autocomplete_fields = ("user", "registration", "dues_period", "tuition_installment")
    readonly_fields = ("created_at", "paid_at")
    date_hierarchy = "created_at"
    inlines = [ReceiptInline]
    actions = ("apply_payment_success",)

    @admin.action(description="Apply payment success (offline / manual — REG-14)")
    def apply_payment_success(self, request, queryset):
        """For PENDING payments (typically OFFLINE), run the same side-effect
        chain the Stripe webhook does: mark SUCCEEDED, flip Registration to
        PAID, create Receipt, send emails. Idempotent."""
        pending = queryset.filter(status=Payment.Status.PENDING)
        skipped = queryset.exclude(status=Payment.Status.PENDING).count()
        succeeded = 0
        for payment in pending:
            complete_payment(payment)
            succeeded += 1
        msg = f"Marked {succeeded} payment(s) succeeded (with receipt + email)."
        if skipped:
            msg += f" Skipped {skipped} not in pending state."
        self.message_user(request, msg, level=messages.SUCCESS)


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
        "dues_amount_pre_candidate",
        "dues_amount_candidate",
        "dues_amount_analyst",
        "block_registration_when_unpaid", "is_current",
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


@admin.register(TuitionPeriod)
class TuitionPeriodAdmin(admin.ModelAdmin):
    list_display = (
        "name", "slug", "start_date", "decision_due_date", "end_date",
        "tuition_amount", "is_current",
    )
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}

    @admin.display(boolean=True, description="Current?")
    def is_current(self, obj):
        from django.utils import timezone
        today = timezone.now().date()
        return obj.start_date <= today <= obj.end_date


class TuitionInstallmentInline(admin.TabularInline):
    model = TuitionInstallment
    extra = 0
    fields = ("sequence", "due_date", "amount", "paid", "paid_at")
    readonly_fields = ("paid_at",)


@admin.register(TuitionEnrollment)
class TuitionEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("user", "tuition_period", "status", "decided_at")
    list_filter = ("tuition_period", "status")
    search_fields = ("user__email", "user__first_name", "user__last_name")
    autocomplete_fields = ("user", "tuition_period")
    readonly_fields = ("decided_at",)
    inlines = [TuitionInstallmentInline]


@admin.register(TuitionInstallment)
class TuitionInstallmentAdmin(admin.ModelAdmin):
    list_display = ("enrollment", "sequence", "due_date", "amount", "paid", "paid_at")
    list_filter = ("paid", "enrollment__tuition_period")
    search_fields = ("enrollment__user__email",)
    autocomplete_fields = ("enrollment",)


@admin.register(RegistrationInstallment)
class RegistrationInstallmentAdmin(admin.ModelAdmin):
    """The treasurer's hand-edit surface for an event payment plan (task #501).

    ``registration_plans.due_installment`` orders by due date rather than
    sequence precisely so a schedule edited here still reads correctly.
    """

    list_display = ("registration", "sequence", "due_date", "amount", "paid", "paid_at")
    list_filter = ("paid", "registration__event")
    search_fields = ("registration__user__email", "registration__event__title")
    autocomplete_fields = ("registration",)


@admin.register(TuitionReminder)
class TuitionReminderAdmin(admin.ModelAdmin):
    list_display = ("user", "tuition_period", "sent_at")
    list_filter = ("tuition_period",)
    search_fields = ("user__email",)
    readonly_fields = ("user", "tuition_period", "sent_at")
    date_hierarchy = "sent_at"


@admin.register(Charge)
class ChargeAdmin(admin.ModelAdmin):
    list_display = ("user", "category", "amount", "status", "effective_date",
                    "source", "staff_adjusted")
    list_filter = ("category", "status", "source", "staff_adjusted")
    search_fields = ("user__email", "user__first_name", "user__last_name", "notes")
    autocomplete_fields = ("user", "dues_period", "tuition_period", "registration")
    date_hierarchy = "effective_date"


@admin.register(LedgerSubmission)
class LedgerSubmissionAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "category", "amount", "claimed_date",
                    "status", "decided_by", "decided_at", "created_at")
    list_filter = ("status", "kind", "category")
    search_fields = ("user__email", "user__first_name", "user__last_name", "details")
    autocomplete_fields = ("user", "decided_by", "created_payment", "created_charge")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"


@admin.register(PaymentMemberAction)
class PaymentMemberActionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "summary", "payment")
    list_filter = ("action",)
    search_fields = ("user__email", "user__first_name", "user__last_name", "summary")
    autocomplete_fields = ("user", "payment")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
