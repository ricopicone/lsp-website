from django.contrib import admin

from .models import Cartel


@admin.register(Cartel)
class CartelAdmin(admin.ModelAdmin):
    list_display = ("__str__", "workgroup")
    search_fields = ("workgroup__name", "workgroup__slug")
    autocomplete_fields = ("workgroup",)
