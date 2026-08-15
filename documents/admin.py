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
        "content_visibility", "effective_date", "is_current_display", "display_order",
    )
    list_filter = ("category", "owning_workgroup", "listing_visibility", "content_visibility")
    search_fields = ("title", "summary", "description", "notice", "body")
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ("superseded_by", "owning_workgroup")
    inlines = [DocumentAuthorInline]
    fieldsets = (
        (None, {"fields": ("title", "slug", "category", "summary", "description")}),
        ("Ownership", {
            "fields": ("owning_workgroup",),
            "description": "The committee or working group that produced this document.",
        }),
        ("Content", {
            "fields": ("file", "body"),
            "description": (
                "Provide a PDF file, or author the content inline as markdown "
                "in the body (leave the file blank). The body supports the "
                "{{ annual_tuition }} placeholder for the current tuition figure."
            ),
        }),
        ("Visibility & ordering", {
            "fields": ("listing_visibility", "content_visibility", "display_order"),
        }),
        ("Status", {"fields": ("notice",)}),
        ("Versioning", {"fields": ("effective_date", "superseded_by")}),
    )

    @admin.display(boolean=True, description="Current")
    def is_current_display(self, obj: Document) -> bool:
        return obj.is_current

    def save_model(self, request, obj, form, change):
        """Record the prior state before an admin edit (task #592).

        Deliberately unlike the staff-path rule of #485/#564: that rule stops
        admin edits from mailing members or moving money, and a snapshot does
        neither. What it prevents is a history reading "no revisions" while the
        PDF has in fact been swapped. ``save_model`` is also the one admin hook
        that knows who is acting.
        """
        if change:
            obj.snapshot_revision(user=request.user, note="Edited in Django admin")
        super().save_model(request, obj, form, change)


@admin.register(DocumentAuthor)
class DocumentAuthorAdmin(admin.ModelAdmin):
    list_display = ("document", "user", "display_order")
    autocomplete_fields = ("document", "user")
    search_fields = (
        "document__title", "user__email", "user__first_name", "user__last_name",
    )
