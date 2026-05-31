from django.contrib import admin

from .models import WorkingGroup


@admin.register(WorkingGroup)
class WorkingGroupAdmin(admin.ModelAdmin):
    list_display = ("__str__", "workgroup")
    search_fields = ("workgroup__name", "workgroup__slug")
    autocomplete_fields = ("workgroup",)
