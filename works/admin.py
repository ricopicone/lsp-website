from django.contrib import admin

from .models import VideoUploadSettings, Work, WorkAuthor, WorkFile


@admin.register(VideoUploadSettings)
class VideoUploadSettingsAdmin(admin.ModelAdmin):
    list_display = ("__str__", "enabled", "max_file_mb")


class WorkAuthorInline(admin.TabularInline):
    model = WorkAuthor
    extra = 1
    autocomplete_fields = ("user",)
    fields = ("user", "display_order")


class WorkFileInline(admin.TabularInline):
    model = WorkFile
    extra = 0
    fields = ("file", "label", "display_order")


@admin.register(Work)
class WorkAdmin(admin.ModelAdmin):
    list_display = (
        "title", "kind", "listing_visibility", "content_visibility",
        "file_count", "publication_date", "submitted_by",
    )
    list_filter = ("kind", "listing_visibility", "content_visibility")
    search_fields = ("title", "abstract", "publication_info", "external_authors")
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ("submitted_by",)
    inlines = [WorkAuthorInline, WorkFileInline]
    fieldsets = (
        (None, {"fields": ("title", "slug", "kind")}),
        ("Visibility", {"fields": ("listing_visibility", "content_visibility")}),
        ("Content", {"fields": ("abstract", "publication_info", "url", "publication_date")}),
        ("Cover", {"fields": ("cover_image",)}),
        ("Authors", {"fields": ("external_authors", "submitted_by")}),
    )

    @admin.display(description="Files")
    def file_count(self, obj: Work) -> int:
        return obj.files.count()


@admin.register(WorkAuthor)
class WorkAuthorAdmin(admin.ModelAdmin):
    list_display = ("work", "user", "display_order")
    autocomplete_fields = ("work", "user")
    search_fields = ("work__title", "user__email", "user__first_name", "user__last_name")


@admin.register(WorkFile)
class WorkFileAdmin(admin.ModelAdmin):
    list_display = ("work", "label", "display_order")
    list_filter = ("work__kind",)
    search_fields = ("work__title", "label")
    autocomplete_fields = ("work",)
