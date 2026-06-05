"""Django admin for Parlêtre.

Staff create channels and categories here and moderate as needed. Threads
and posts are created by members through the board UI, but appear here
(read-mostly) for moderation and audit.
"""

from __future__ import annotations

from django.contrib import admin

from .models import (
    Attachment,
    Channel,
    ChannelCategory,
    DigestPreference,
    InboundEmail,
    Notification,
    Post,
    Reaction,
    ReadMarker,
    Subscription,
    Thread,
)


@admin.register(ChannelCategory)
class ChannelCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "position", "slug")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("position", "name")


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "kind", "category", "access", "post_policy", "archived")
    list_filter = ("kind", "access", "post_policy", "archived", "category")
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("members", "moderators")
    raw_id_fields = ("created_by",)
    fieldsets = (
        (None, {"fields": ("name", "slug", "category", "kind", "description")}),
        (
            "Access",
            {
                "fields": (
                    "access", "allowed_roles", "committee",
                    "members", "moderators", "created_by",
                ),
                "description": "allowed_roles applies when access=Specific roles; "
                "committee when access=Committee; members when access=Private. "
                "created_by is the member who made a private chat (may delete it).",
            },
        ),
        (
            "Posting & subscriptions",
            {"fields": ("post_policy", "auto_subscribe", "default_subscription_level")},
        ),
        (
            "Disappearing messages",
            {
                "fields": ("message_ttl_seconds",),
                "description": "Set a TTL (seconds) to make this a disappearing chat "
                "— messages vanish that long after posting. Leave blank for permanent.",
            },
        ),
        (
            "Video",
            {
                "fields": ("recording_mode",),
                "description": "For video channels: set to Off to remove the Record "
                "button (e.g. The Gaze, an open all-member room).",
            },
        ),
        ("Display", {"fields": ("position", "archived")}),
    )


class PostInline(admin.TabularInline):
    model = Post
    fields = ("author", "body", "via_email", "deleted", "created_at")
    readonly_fields = ("created_at",)
    extra = 0


@admin.register(Thread)
class ThreadAdmin(admin.ModelAdmin):
    list_display = (
        "title", "channel", "author", "pinned", "locked", "resolved", "last_activity_at",
    )
    list_filter = ("channel", "pinned", "locked", "resolved")
    search_fields = ("title", "slug")
    raw_id_fields = ("channel", "author")
    inlines = [PostInline]


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("__str__", "channel", "author", "via_email", "deleted", "created_at")
    list_filter = ("channel", "via_email", "deleted")
    search_fields = ("body",)
    raw_id_fields = ("channel", "thread", "author", "reply_to")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "channel", "level", "updated_at")
    list_filter = ("level", "channel")
    raw_id_fields = ("user", "channel")


@admin.register(Reaction)
class ReactionAdmin(admin.ModelAdmin):
    list_display = ("emoji", "post", "user", "created_at")
    raw_id_fields = ("post", "user")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "verb", "actor", "read_at", "created_at")
    list_filter = ("verb",)
    raw_id_fields = ("recipient", "actor", "post", "thread")


@admin.register(ReadMarker)
class ReadMarkerAdmin(admin.ModelAdmin):
    list_display = ("user", "thread", "channel", "last_read_at")
    raw_id_fields = ("user", "thread", "channel")


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ("original_name", "post", "content_type", "size", "uploaded_at")
    raw_id_fields = ("post",)


@admin.register(DigestPreference)
class DigestPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "frequency", "last_sent_at")
    list_filter = ("frequency",)
    raw_id_fields = ("user",)


@admin.register(InboundEmail)
class InboundEmailAdmin(admin.ModelAdmin):
    list_display = ("created_at", "status", "user", "post", "message_id")
    list_filter = ("status",)
    search_fields = ("message_id",)
    raw_id_fields = ("user", "post")
