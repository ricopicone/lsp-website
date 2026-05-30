from django.contrib import admin

from .models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "title", "category", "visibility",
        "effective_date", "is_current_display", "display_order",
    )
    list_filter = ("category", "visibility")
    search_fields = ("title", "summary", "description")
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ("superseded_by",)
    fieldsets = (
        (None, {"fields": ("title", "slug", "category", "summary", "description")}),
        ("File", {"fields": ("file",)}),
        ("Visibility & ordering", {"fields": ("visibility", "display_order")}),
        ("Versioning", {"fields": ("effective_date", "superseded_by")}),
    )
    readonly_fields = ()

    @admin.display(boolean=True, description="Current")
    def is_current_display(self, obj: Document) -> bool:
        return obj.is_current
