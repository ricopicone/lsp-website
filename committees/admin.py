from django.contrib import admin

from .models import Committee


@admin.register(Committee)
class CommitteeAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "public", "active_member_count")
    list_filter = ("public",)
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("workgroup",)
    help_text = "Membership is managed on the attached workgroup."

    @admin.display(description="Active members")
    def active_member_count(self, obj):
        return obj.active_members().count()
