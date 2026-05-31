from django.contrib import admin

from .models import Document, DocumentAuthor


class DocumentAuthorInline(admin.TabularInline):
    model = DocumentAuthor
    extra = 1
    autocomplete_fields = ("user",)
    fields = ("user", "display_order")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "title", "category", "owning_workgroup", "listing_visibility",
        "pdf_visibility", "effective_date", "is_current_display", "display_order",
    )
    list_filter = ("category", "owning_workgroup", "listing_visibility", "pdf_visibility")
    search_fields = ("title", "summary", "description", "notice")
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ("superseded_by", "owning_workgroup")
    inlines = [DocumentAuthorInline]
    fieldsets = (
        (None, {"fields": ("title", "slug", "category", "summary", "description")}),
        ("Ownership", {
            "fields": ("owning_workgroup",),
            "description": "The committee or working group that produced this document.",
        }),
        ("File", {"fields": ("file",)}),
        ("Visibility & ordering", {
            "fields": ("listing_visibility", "pdf_visibility", "display_order"),
        }),
        ("Status", {"fields": ("notice",)}),
        ("Versioning", {"fields": ("effective_date", "superseded_by")}),
    )

    @admin.display(boolean=True, description="Current")
    def is_current_display(self, obj: Document) -> bool:
        return obj.is_current


@admin.register(DocumentAuthor)
class DocumentAuthorAdmin(admin.ModelAdmin):
    list_display = ("document", "user", "display_order")
    autocomplete_fields = ("document", "user")
    search_fields = (
        "document__title", "user__email", "user__first_name", "user__last_name",
    )
