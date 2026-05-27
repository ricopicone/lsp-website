from django.contrib import admin

from .models import Committee, CommitteeMembership


class CommitteeMembershipInline(admin.TabularInline):
    model = CommitteeMembership
    extra = 0
    autocomplete_fields = ("user",)
    fields = ("user", "role_in_committee", "start_date", "end_date")


@admin.register(Committee)
class CommitteeAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "public", "active_member_count")
    list_filter = ("public",)
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [CommitteeMembershipInline]

    @admin.display(description="Active members")
    def active_member_count(self, obj):
        return obj.active_members().count()


@admin.register(CommitteeMembership)
class CommitteeMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "committee", "role_in_committee", "start_date", "end_date")
    list_filter = ("committee", "role_in_committee")
    autocomplete_fields = ("user",)
    search_fields = ("user__email", "user__first_name", "user__last_name", "committee__name")
    date_hierarchy = "start_date"
