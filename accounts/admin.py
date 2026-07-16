from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .forms import UserChangeForm, UserCreationForm
from .models import (
    Advisorship,
    EmailChangeRequest,
    MemberIntakeSurvey,
    MembershipTenure,
    Profile,
    TOTPDevice,
    User,
)


class ProfileAdminForm(forms.ModelForm):
    """Blocks a staff-edited Profile.role change that would promote a
    tuition-owing in-training member out of training (task #439's tuition
    gate, mirrored here since the Django admin bypasses
    record_membership_change)."""

    class Meta:
        model = Profile
        fields = "__all__"

    def clean_role(self):
        role = self.cleaned_data["role"]
        if self.instance.pk and role != self.instance.role:
            from django.core.exceptions import ValidationError

            from .membership import validate_role_transition
            try:
                validate_role_transition(self.instance.user, role)
            except ValidationError as exc:
                raise forms.ValidationError(" ".join(exc.messages))
        return role


class ProfileInline(admin.StackedInline):
    model = Profile
    form = ProfileAdminForm
    fk_name = "user"  # Profile also has persona_owner → must disambiguate.
    can_delete = False
    fields = (
        "role",
        "is_faculty",
        "default_billing_mode",
        "public",
        "bio",
        "headshot",
        "notes",
    )
    verbose_name_plural = "Profile"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin for the email-based user model."""

    add_form = UserCreationForm
    form = UserChangeForm
    inlines = [ProfileInline]
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "is_staff", "is_active")
    list_filter = ("is_staff", "is_superuser", "is_active", "groups")
    search_fields = ("email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2"),
            },
        ),
    )

    def get_inline_instances(self, request, obj=None):
        # Profiles are created by a signal; show the inline only when editing.
        if obj is None:
            return []
        return super().get_inline_instances(request, obj)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    form = ProfileAdminForm
    list_display = ("user", "role", "is_faculty", "clinical_background")
    list_filter = ("role", "is_faculty", "public", "clinical_background")
    search_fields = ("user__email", "user__first_name", "user__last_name")

    def save_model(self, request, obj, form, change):
        # Profile.save() invalidates the geocode when ``location`` changes;
        # re-resolve it here so an admin edit updates the map pin immediately
        # instead of leaving a stale one (task #391).
        super().save_model(request, obj, form, change)
        from .geocoding import geocode_after_edit

        geocode_after_edit(obj)


@admin.register(EmailChangeRequest)
class EmailChangeRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "new_email", "created_at", "confirmed_at")
    list_filter = ("confirmed_at",)
    search_fields = ("user__email", "new_email")
    readonly_fields = ("user", "new_email", "token", "created_at", "confirmed_at")

    def has_add_permission(self, request):
        return False


@admin.register(TOTPDevice)
class TOTPDeviceAdmin(admin.ModelAdmin):
    """Audit + lockout-recovery for 2FA. Delete a row to reset a member's
    authenticator (they'll re-enroll on next login when enforcement is on).
    The shared ``secret`` is never shown."""

    list_display = ("user", "confirmed", "created_at", "last_used_at")
    list_filter = ("confirmed",)
    search_fields = ("user__email", "user__first_name", "user__last_name")
    readonly_fields = ("user", "confirmed", "created_at", "last_used_at")
    exclude = ("secret",)

    def has_add_permission(self, request):
        return False


@admin.register(MembershipTenure)
class MembershipTenureAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "start_ay", "end_ay", "source")
    list_filter = ("role", "source")
    search_fields = ("user__email", "user__first_name", "user__last_name")
    autocomplete_fields = ("user",)


@admin.register(MemberIntakeSurvey)
class MemberIntakeSurveyAdmin(admin.ModelAdmin):
    list_display = ("user", "submitted_at", "year_joined", "applied_at")
    list_filter = ("submitted_at", "applied_at")
    search_fields = ("user__email", "user__first_name", "user__last_name")
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at",)


@admin.register(Advisorship)
class AdvisorshipAdmin(admin.ModelAdmin):
    list_display = ("advisee", "advisor", "start_date", "end_date")
    list_filter = ("start_date",)
    search_fields = (
        "advisee__email", "advisee__last_name", "advisor__email", "advisor__last_name",
    )
    autocomplete_fields = ("advisee", "advisor")
