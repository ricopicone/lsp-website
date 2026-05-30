from django.contrib import admin

from .models import Work, WorkAuthor


class WorkAuthorInline(admin.TabularInline):
    model = WorkAuthor
    extra = 1
    autocomplete_fields = ("user",)
    fields = ("user", "display_order")


@admin.register(Work)
class WorkAdmin(admin.ModelAdmin):
    list_display = (
        "title", "kind", "listing_visibility", "pdf_visibility",
        "publication_date", "submitted_by",
    )
    list_filter = ("kind", "listing_visibility", "pdf_visibility")
    search_fields = ("title", "abstract", "publication_info", "external_authors")
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ("submitted_by",)
    inlines = [WorkAuthorInline]
    fieldsets = (
        (None, {"fields": ("title", "slug", "kind")}),
        ("Visibility", {"fields": ("listing_visibility", "pdf_visibility")}),
        ("Content", {"fields": ("abstract", "publication_info", "url", "publication_date")}),
        ("Files", {"fields": ("pdf", "cover_image")}),
        ("Authors", {"fields": ("external_authors", "submitted_by")}),
    )


@admin.register(WorkAuthor)
class WorkAuthorAdmin(admin.ModelAdmin):
    list_display = ("work", "user", "display_order")
    autocomplete_fields = ("work", "user")
    search_fields = ("work__title", "user__email", "user__first_name", "user__last_name")
