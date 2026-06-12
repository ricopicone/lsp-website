from django.contrib import admin

from .models import DevApiToken


@admin.register(DevApiToken)
class DevApiTokenAdmin(admin.ModelAdmin):
    list_display = ("label", "user", "prefix", "revoked", "last_used_at", "created_at")
    list_filter = ("revoked",)
    search_fields = ("label", "user__email", "prefix")
    readonly_fields = ("token_hash", "prefix", "created_at", "last_used_at")
    autocomplete_fields = ("user",)

    # The raw token is never recoverable; mint new ones with the management
    # command (``manage.py create_devapi_token``). The admin only revokes.
    def has_add_permission(self, request):
        return False
